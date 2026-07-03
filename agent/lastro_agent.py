#!/usr/bin/env python3
"""
lastro-agent : afere a saude do equipamento e emite um laudo.json.

Este e o UNICO componente que toca o hardware. O site (GitHub Pages) nunca le
hardware; ele so renderiza o laudo que este agente comita. E dai que nasce a
confianca do selo: o dado nasce local, o GitHub so carimba o commit.

Regra de ouro: se uma leitura falhar (sem sudo, sem smartctl, plataforma sem
suporte), o agente PARA com instrucao clara. Nunca inventa um numero. Orgaos
opcionais sem leitor na plataforma sao OMITIDOS do laudo, jamais preenchidos.

Uso:
    python3 lastro_agent.py --emitir             # imprime o laudo no stdout
    python3 lastro_agent.py --emitir --commit    # emite, grava e comita na Caderneta

Plataformas no v1: SSD via smartctl (Linux primeiro; funciona onde o
smartmontools existir), bateria via /sys (Linux), memoria via psutil.
Termico fica fora do v1 (SPEC, secao Leitura).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys

SCHEMA_VERSAO = "1"
AGENTE_VERSAO = "1.4.0"
RAIZ = pathlib.Path(__file__).resolve().parent.parent   # raiz do repo do passaporte
LAUDOS_DIR = RAIZ / "data" / "laudos"
CADERNETA = RAIZ / "data" / "caderneta.json"
LATEST = RAIZ / "data" / "latest.json"


class LeituraError(RuntimeError):
    """Leitura de hardware que falhou. O agente para: laudo sem dado real nao existe."""


def _sha256_de_mim() -> str:
    """sha256 do proprio arquivo, para proveniencia no laudo."""
    with open(__file__, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------- identidade

def _ids_estaveis() -> list[str]:
    """Identificadores estaveis da placa, por plataforma. Entram apenas no hash,
    nunca no laudo em claro (privacidade, SPEC secao 8)."""
    ids: list[str] = []
    so = platform.system()
    if so == "Linux":
        for p in ("/sys/class/dmi/id/product_uuid", "/etc/machine-id"):
            try:
                v = pathlib.Path(p).read_text().strip()
                if v:
                    ids.append(v)
            except OSError:
                pass
    elif so == "Windows":
        try:
            v = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            if v and v != "00000000-0000-0000-0000-000000000000":
                ids.append(v)
        except Exception:
            pass
    elif so == "Darwin":
        try:
            saida = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                   capture_output=True, text=True, timeout=20).stdout
            for linha in saida.splitlines():
                if "IOPlatformUUID" in linha:
                    ids.append(linha.split('"')[-2])
        except Exception:
            pass
    return ids


def _serie_anonima() -> str:
    """Serie BR-XX-XXXX: sha256 de identificadores de placa. Estavel entre
    afericoes da mesma maquina, irreversivel para quem le o laudo."""
    ids = _ids_estaveis()
    if not ids:
        raise LeituraError(
            "nao consegui ler um identificador estavel da placa nesta plataforma.\n"
            "Sem serie estavel nao ha passaporte: a caderneta perderia a continuidade.")
    h = hashlib.sha256("|".join(ids).encode()).hexdigest().upper()
    return f"BR-{h[:2]}-{h[2:6]}"


# ------------------------------------------------------------------- maquina

def _modelo_placa() -> str | None:
    so = platform.system()
    try:
        if so == "Linux":
            return pathlib.Path("/sys/class/dmi/id/product_name").read_text().strip() or None
        if so == "Windows":
            return subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_ComputerSystem).Model"],
                capture_output=True, text=True, timeout=20).stdout.strip() or None
        if so == "Darwin":
            saida = subprocess.run(["sysctl", "-n", "hw.model"],
                                   capture_output=True, text=True, timeout=20).stdout.strip()
            return saida or None
    except Exception:
        pass
    return None


def ler_maquina(armazenamento_gb: float | None) -> dict:
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / (1024 ** 3))
    except ImportError:
        ram_gb = None
    so = platform.system()
    versao = platform.release()
    if so == "Linux":
        try:  # nome amigavel da distro, se houver
            for linha in pathlib.Path("/etc/os-release").read_text().splitlines():
                if linha.startswith("PRETTY_NAME="):
                    so, versao = linha.split("=", 1)[1].strip('"'), ""
        except OSError:
            pass
    return {
        "modelo": _modelo_placa() or "modelo desconhecido",
        "cpu": platform.processor() or platform.machine() or "desconhecido",
        "ram_gb": ram_gb,
        "armazenamento_gb": armazenamento_gb,
        "so": f"{so} {versao}".strip(),
        "comprado_em": None,   # opcional, informado pelo usuario (v2: arquivo de config)
    }


# ----------------------------------------------------------------- SSD/SMART

def _smartctl(*args: str) -> dict:
    exe = shutil.which("smartctl")
    if not exe:
        raise LeituraError(
            "smartctl nao encontrado. O desgaste do SSD e a leitura obrigatoria do laudo.\n"
            "Instale smartmontools:\n"
            "  Ubuntu/Debian : sudo apt install smartmontools\n"
            "  macOS         : brew install smartmontools\n"
            "  Windows       : choco install smartmontools")
    proc = subprocess.run([exe, "-j", *args], capture_output=True, text=True, timeout=60)
    try:
        dados = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise LeituraError(f"smartctl devolveu saida inesperada: {proc.stdout[:200]!r}")
    for msg in dados.get("smartctl", {}).get("messages", []):
        texto = msg.get("string", "")
        if msg.get("severity") == "error" and ("Permission denied" in texto or "denied" in texto):
            raise LeituraError(
                "sem permissao para ler o SMART do disco.\n"
                "Rode com privilegio: sudo python3 agent/lastro_agent.py --emitir\n"
                "(no Windows, abra o terminal como administrador)")
    return dados


def ler_ssd() -> tuple[dict, float | None]:
    """Desgaste do SSD via SMART. Orgao OBRIGATORIO: sem ele nao ha laudo.
    NVMe: percentage_used direto. SATA: wear leveling normalizado (attr 177/233).
    Retorna (orgao, capacidade_gb) para reaproveitar a capacidade na identidade."""
    scan = _smartctl("--scan")
    dispositivos = scan.get("devices", [])
    if not dispositivos:
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            raise LeituraError(
                "nenhum disco visivel sem privilegio.\n"
                "Rode com sudo: sudo python3 agent/lastro_agent.py --emitir")
        raise LeituraError("smartctl nao encontrou nenhum disco nesta maquina.")

    for disp in dispositivos:
        nome = disp.get("name")
        dados = _smartctl("-A", "-i", nome)
        desgaste = valor_cru = None

        nvme = dados.get("nvme_smart_health_information_log")
        if nvme and nvme.get("percentage_used") is not None:
            pct = nvme["percentage_used"]
            desgaste = min(pct / 100.0, 1.0)
            valor_cru = f"Percentage Used: {pct}%"
        else:
            tabela = dados.get("ata_smart_attributes", {}).get("table", [])
            attr = next((a for a in tabela if a.get("id") in (177, 233)), None)
            if attr:  # value normalizado: 100 = novo, 0 = fim de vida
                desgaste = max(0.0, min(1.0, 1 - attr["value"] / 100.0))
                valor_cru = f"{attr['name']}: {attr['value']}/100"

        if desgaste is None:
            continue
        cap = dados.get("user_capacity", {}).get("bytes")
        return ({
            "desgaste": round(desgaste, 3),
            "valor_cru": valor_cru,
            "estado": _estado(desgaste, atencao=0.4, critico=0.6),
        }, round(cap / 1e9) if cap else None)

    raise LeituraError(
        "nenhum disco expos indicador de desgaste SMART (NVMe percentage_used\n"
        "ou ATA wear leveling). Sem leitura real nao ha laudo; discos rigidos\n"
        "e controladoras sem SMART nao tem suporte no v1.")


# ------------------------------------------------------------ demais orgaos

def ler_bateria() -> dict | None:
    """Recargas + saude via /sys (Linux). None = sem bateria ou plataforma sem
    leitor no v1: o orgao e omitido do laudo, nunca preenchido no chute.
    Formula transparente: fim de vida = 70% da capacidade de projeto, entao
    desgaste = (100 - saude_pct) / 30, limitado a 0..1."""
    if platform.system() != "Linux":
        return None
    for bat in sorted(pathlib.Path("/sys/class/power_supply").glob("BAT*")):
        def le(nome: str) -> str | None:
            try:
                return (bat / nome).read_text().strip()
            except OSError:
                return None
        cheia = le("energy_full") or le("charge_full")
        projeto = le("energy_full_design") or le("charge_full_design")
        if not (cheia and projeto and int(projeto) > 0):
            continue
        saude = round(int(cheia) / int(projeto) * 100, 1)
        desgaste = round(max(0.0, min(1.0, (100 - saude) / 30)), 3)
        orgao = {"desgaste": desgaste, "saude_pct": saude,
                 "estado": _estado(desgaste, atencao=0.5, critico=0.8)}
        recargas = le("cycle_count")
        if recargas and int(recargas) > 0:
            orgao["recargas"] = int(recargas)
        return orgao
    return None


def ler_memoria() -> dict | None:
    """Proxy de pressao, transparente: fracao de RAM ocupada sob a carga atual,
    com flag de swap se houve paginacao desde o boot. None se psutil faltar."""
    try:
        import psutil
    except ImportError:
        return None
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    swap_frequente = sw.total > 0 and (sw.sin + sw.sout) > 0
    desgaste = round(min(1.0, vm.percent / 100), 2)
    return {"desgaste": desgaste, "swap_frequente": swap_frequente,
            "estado": _estado(desgaste, atencao=0.7, critico=0.9)}


def _estado(d: float, atencao: float, critico: float) -> str:
    return "critico" if d >= critico else "atencao" if d >= atencao else "saudavel"


# --------------------------------------------------------------- prognostico

def _historico_real() -> list[dict]:
    """Laudos ja gravados na Caderneta, ignorando dados de exemplo. Enquanto o
    manifesto disser sample=true, a caderneta ainda e demonstracao."""
    try:
        manifesto = json.loads(CADERNETA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if manifesto.get("sample"):
        return []
    laudos = []
    for nome in manifesto.get("laudos", []):
        try:
            laudos.append(json.loads((LAUDOS_DIR / nome).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    laudos.sort(key=lambda l: l["aferido_em"])
    return laudos


def calcular_prognostico(laudo: dict, historico: list[dict]) -> dict | None:
    """Formula legivel, sem caixa-preta (SPEC secao 6):
      taxa do orgao   = (desgaste de agora - desgaste da 1a afericao) / meses entre elas
      meses restantes = (1 - desgaste de agora) / taxa
      gargalo         = o orgao que zera primeiro
      margem          = 20% da estimativa (historico curto = incerteza alta)
    So estima com 2+ afericoes reais da MESMA serie. Sem historico, sem numero."""
    pontos = [l for l in historico if l.get("serie") == laudo["serie"]]
    if not pontos:
        return None
    primeira = dt.datetime.fromisoformat(pontos[0]["aferido_em"].replace("Z", "+00:00"))
    agora = dt.datetime.fromisoformat(laudo["aferido_em"].replace("Z", "+00:00"))
    meses = (agora - primeira).days / 30.44
    if meses <= 0:
        return None

    gargalo = None
    for nome, orgao in laudo["orgaos"].items():
        antigo = pontos[0]["orgaos"].get(nome)
        if antigo is None:
            continue
        taxa = (orgao["desgaste"] - antigo["desgaste"]) / meses
        if taxa <= 0:
            continue
        restantes = (1 - orgao["desgaste"]) / taxa
        if gargalo is None or restantes < gargalo[1]:
            gargalo = (nome, restantes)
    if gargalo is None:
        return None

    prognostico = {
        "meses_restantes": round(gargalo[1]),
        "margem_meses": max(1, round(gargalo[1] * 0.2)),
        "gargalo": gargalo[0],
    }
    try:  # base amostral: quantas maquinas do mesmo modelo o Observatorio conhece
        obs = json.loads((RAIZ / "data" / "observatorio.json").read_text(encoding="utf-8"))
        modelo = obs.get("modelos", {}).get(laudo["maquina"]["modelo"])
        if modelo and modelo.get("amostra"):
            prognostico["base_amostral"] = modelo["amostra"]
    except (OSError, json.JSONDecodeError):
        pass
    return prognostico


# --------------------------------------------------------------------- laudo

def montar_laudo() -> dict:
    ssd, capacidade_gb = ler_ssd()
    orgaos = {"ssd": ssd}
    for nome, leitor in (("bateria", ler_bateria), ("memoria", ler_memoria)):
        orgao = leitor()
        if orgao is not None:
            orgaos[nome] = orgao
    laudo = {
        "versao": SCHEMA_VERSAO,
        "serie": _serie_anonima(),
        "maquina": ler_maquina(capacidade_gb),
        "aferido_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "agente": {"nome": "lastro-agent", "versao": AGENTE_VERSAO, "sha256": _sha256_de_mim()},
        "orgaos": orgaos,
    }
    prognostico = calcular_prognostico(laudo, _historico_real())
    if prognostico:
        laudo["prognostico"] = prognostico
    return laudo


def _json_bonito(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def comitar(laudo: dict):
    """Grava o laudo na Caderneta e comita. O commit e o carimbo de cartorio:
    e ele, e nao o campo aferido_em, que da a garantia inforjavel. Na primeira
    afericao real, os dados de exemplo saem da caderneta (serie de outra maquina
    nao pode conviver com a sua)."""
    if not (RAIZ / ".git").exists():
        raise LeituraError(
            "esta pasta nao e um repositorio git: sem commit nao ha carimbo.\n"
            f"Rode `git init` em {RAIZ} (ou clone seu repo de passaporte).")

    try:
        manifesto = json.loads(CADERNETA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifesto = {"sample": True, "laudos": []}

    if manifesto.get("sample"):
        print("primeira afericao real: removendo os laudos de exemplo da caderneta.")
        for nome in manifesto.get("laudos", []):
            (LAUDOS_DIR / nome).unlink(missing_ok=True)
        manifesto["laudos"] = []
        manifesto["sample"] = False
        manifesto["descricao"] = ("Indice da Caderneta, mantido pelo lastro-agent "
                                  "a cada --commit. O site descobre os laudos por aqui.")

    nome = f"{laudo['aferido_em'][:10]}.json"     # re-afericao no mesmo dia sobrescreve
    LAUDOS_DIR.mkdir(parents=True, exist_ok=True)
    (LAUDOS_DIR / nome).write_text(_json_bonito(laudo), encoding="utf-8")
    if nome not in manifesto["laudos"]:
        manifesto["laudos"].append(nome)
    manifesto["laudos"].sort()
    LATEST.write_text(_json_bonito(laudo), encoding="utf-8")
    CADERNETA.write_text(_json_bonito(manifesto), encoding="utf-8")

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True)

    git("add", str(LAUDOS_DIR / nome), str(LATEST), str(CADERNETA))
    msg = f"laudo: afericao {laudo['aferido_em'][:10]} (serie {laudo['serie']})"
    r = git("commit", "-m", msg)
    if r.returncode != 0:
        raise LeituraError(f"git commit falhou:\n{r.stdout}{r.stderr}")
    sha = git("rev-parse", "--short", "HEAD").stdout.strip()
    print(f"laudo comitado: {sha} \"{msg}\"")

    r = git("push")
    if r.returncode == 0:
        print("push feito: o carimbo publico do GitHub ja vale.")
    else:
        print("push nao foi possivel agora (sem remoto ou sem rede).\n"
              "O laudo esta comitado localmente; o carimbo so vale como prova "
              "publica depois do push.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="lastro-agent")
    p.add_argument("--emitir", action="store_true", help="gera e imprime o laudo")
    p.add_argument("--commit", action="store_true", help="grava o laudo na Caderneta e comita")
    args = p.parse_args(argv)

    if not args.emitir:
        p.print_help()
        return 0

    try:
        laudo = montar_laudo()
    except LeituraError as e:
        print(f"lastro-agent: leitura falhou, nenhum laudo foi gerado.\n{e}", file=sys.stderr)
        return 1

    print(json.dumps(laudo, ensure_ascii=False, indent=2))
    if args.commit:
        try:
            comitar(laudo)
        except LeituraError as e:
            print(f"lastro-agent: o laudo foi gerado, mas nao foi comitado.\n{e}",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
