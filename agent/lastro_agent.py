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
AGENTE_VERSAO = "1.6.0"
RAIZ = pathlib.Path(__file__).resolve().parent.parent   # raiz do repo do passaporte
LAUDOS_DIR = RAIZ / "data" / "laudos"
CADERNETA = RAIZ / "data" / "caderneta.json"
LATEST = RAIZ / "data" / "latest.json"


class LeituraError(RuntimeError):
    """Leitura de hardware que falhou. O agente para: laudo sem dado real nao existe."""


def _sha256_de_mim() -> str:
    """sha256 do artefato que esta rodando, para proveniencia no laudo. No exe
    empacotado, e o hash do executavel; no script, do .py com fins de linha
    normalizados (a mesma release tem o mesmo hash em qualquer checkout)."""
    alvo = sys.executable if getattr(sys, "frozen", False) else __file__
    with open(alvo, "rb") as f:
        conteudo = f.read()
    if not getattr(sys, "frozen", False):
        conteudo = conteudo.replace(b"\r\n", b"\n")
    return hashlib.sha256(conteudo).hexdigest()


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

def _acha_smartctl() -> str | None:
    """Procura o smartctl no pacote do exe, no PATH e, no Windows, na pasta
    padrao de instalacao (instalacao recem-feita nao entra no PATH da sessao)."""
    if getattr(sys, "frozen", False):
        embutido = pathlib.Path(getattr(sys, "_MEIPASS", "")) / "smartmontools" / "smartctl.exe"
        if embutido.exists():
            return str(embutido)
    exe = shutil.which("smartctl")
    if exe:
        return exe
    if platform.system() == "Windows":
        for cand in (r"C:\Program Files\smartmontools\bin\smartctl.exe",
                     r"C:\Program Files (x86)\smartmontools\bin\smartctl.exe"):
            if pathlib.Path(cand).exists():
                return cand
    return None


def _instrucao_instalar_smart() -> str:
    so = platform.system()
    if so == "Windows":
        return ("Num PowerShell aberto COMO ADMINISTRADOR (botao direito no PowerShell,\n"
                "'Executar como administrador'), rode:\n"
                "  winget install smartmontools.smartmontools\n"
                "  (ou: choco install smartmontools -y)\n"
                "e depois rode o lastro-agent de novo, no mesmo terminal de administrador.")
    if so == "Darwin":
        return "Instale com: brew install smartmontools"
    return "Instale com: sudo apt install smartmontools (ou o equivalente da sua distro)"


def _windows_sem_admin() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() == 0
    except Exception:
        return False


def _smartctl(*args: str) -> dict:
    exe = _acha_smartctl()
    if not exe:
        raise LeituraError(
            "smartctl nao encontrado. O desgaste do SSD e a leitura obrigatoria do laudo.\n"
            + _instrucao_instalar_smart())
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
    if _acha_smartctl() and _windows_sem_admin():
        raise LeituraError(
            "no Windows a leitura SMART exige administrador.\n"
            "Feche este terminal, abra o PowerShell com botao direito >\n"
            "'Executar como administrador', volte a esta pasta e rode o comando de novo.")
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


# ----------------------------------- emissao sem conta (carimbo publico Rekor)
# Para quem nao tem (nem quer ter) GitHub: o hash do laudo e depositado no
# Rekor, o diario publico e append-only do projeto Sigstore (Linux Foundation).
# O deposito nao exige conta; o timestamp do log e o carimbo de cartorio.
# O resultado e um certificado-arquivo autocontido que o comprador confere
# no site (conferir.html) contra o proprio log publico.

REKOR = "https://rekor.sigstore.dev"


def _dados_dir() -> pathlib.Path:
    """Caderneta local (modo sem conta): onde o historico desta maquina vive."""
    so = platform.system()
    if so == "Windows":
        base = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home()))
    elif so == "Darwin":
        base = pathlib.Path.home() / "Library" / "Application Support"
    else:
        base = pathlib.Path(os.environ.get("XDG_DATA_HOME",
                                           pathlib.Path.home() / ".local" / "share"))
    d = base / "Lastro" / "laudos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _caderneta_local(serie: str) -> list[dict]:
    laudos = []
    for arq in sorted(_dados_dir().glob("*.json")):
        try:
            l = json.loads(arq.read_text(encoding="utf-8"))
            if l.get("serie") == serie:
                laudos.append(l)
        except (OSError, json.JSONDecodeError):
            pass
    laudos.sort(key=lambda l: l["aferido_em"])
    return laudos


def _carimbar_rekor(conteudo: bytes) -> dict:
    """Deposita o sha256 do laudo no Rekor e retorna o recibo do carimbo.
    A chave e efemera (gerada e descartada): ela so satisfaz o formato do log;
    quem da fe e o timestamp do diario publico, nao a chave."""
    import base64
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        raise LeituraError("falta a biblioteca 'cryptography' para o carimbo publico.\n"
                           "Instale com: pip install cryptography")
    chave = ec.generate_private_key(ec.SECP256R1())
    assinatura = chave.sign(conteudo, ec.ECDSA(hashes.SHA256()))
    pub_pem = chave.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    digesto = hashlib.sha256(conteudo).hexdigest()
    resposta = _api(f"{REKOR}/api/v1/log/entries", dados={
        "apiVersion": "0.0.1", "kind": "hashedrekord",
        "spec": {
            "data": {"hash": {"algorithm": "sha256", "value": digesto}},
            "signature": {
                "content": base64.b64encode(assinatura).decode(),
                "publicKey": {"content": base64.b64encode(pub_pem).decode()},
            },
        }})
    uuid, entrada = next(iter(resposta.items()))
    return {"registro": "rekor.sigstore.dev", "uuid": uuid,
            "indice": entrada.get("logIndex"),
            "integrado_em": dt.datetime.fromtimestamp(
                entrada["integratedTime"], dt.timezone.utc).isoformat(timespec="seconds"),
            "sha256": digesto}


_CERT_MODELO = """<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lastro · certificado {serie}</title>
<style>
  :root{{--cedula:#E6E9DC;--tinta:#15251C;--soft:#3a4d41;--verde:#1E7B45;--ambar:#A9741A;--oxb:#8C2A22;
        --linha:rgba(21,37,28,.16);--linhaf:rgba(21,37,28,.34)}}
  *{{box-sizing:border-box}}
  body{{margin:0;min-height:100vh;background:radial-gradient(120% 90% at 50% -10%,#16261d,#0e1a14 60%,#0a130e);
       font-family:Georgia,'Times New Roman',serif;color:var(--tinta);display:flex;justify-content:center;
       align-items:flex-start;padding:34px 16px 60px;line-height:1.5}}
  .doc{{width:100%;max-width:560px;background:var(--cedula);border:1px solid rgba(0,0,0,.35);
       box-shadow:0 40px 80px -30px rgba(0,0,0,.7);position:relative;padding:24px 26px 26px}}
  .doc::after{{content:"";position:absolute;inset:8px;border:1.5px solid var(--linhaf);pointer-events:none}}
  .mono{{font-family:'Courier New',monospace}}
  .topo{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1.5px solid var(--linhaf);
        padding-bottom:12px;margin-bottom:14px}}
  .marca{{font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:15px}}
  .kicker{{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--soft)}}
  .serie{{text-align:right;font-size:10.5px;color:var(--soft);line-height:1.7}}
  .serie b{{color:var(--tinta)}}
  h1{{font-size:19px;margin:0}}
  .specs{{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--soft);margin:2px 0 14px}}
  .prog{{text-align:center;margin:14px 0 16px}}
  .prog .rotulo{{font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:var(--soft)}}
  .prog .valor{{font-size:34px;font-weight:700;margin:4px 0 2px}}
  .prog .sub{{font-size:12.5px}}
  table{{width:100%;border-collapse:collapse;font-size:12.5px;margin:6px 0 14px}}
  td{{padding:6px 0;border-bottom:1px solid var(--linha)}}
  td.d{{text-align:right;font-weight:700}} td.d .mono{{font-size:11.5px}}
  .medidor{{height:6px;background:rgba(21,37,28,.09);border:1px solid var(--linha);margin-top:4px}}
  .medidor i{{display:block;height:100%}}
  .ok{{background:var(--verde)}} .warn{{background:var(--ambar)}} .bad{{background:var(--oxb)}}
  .selo{{border-top:1.5px solid var(--linhaf);padding-top:14px;font-size:11px}}
  .selo h3{{margin:0 0 6px;font-size:14px}}
  .selo dl{{margin:0;display:grid;grid-template-columns:auto 1fr;gap:2px 10px;font-size:10.5px}}
  .selo dt{{color:var(--soft)}} .selo dd{{margin:0;font-weight:700;overflow-wrap:anywhere}}
  .conferir{{margin-top:12px;border:1.5px solid var(--linhaf);background:rgba(30,123,69,.07);padding:10px 12px;font-size:12px}}
  .conferir a{{color:var(--verde)}}
  .micro{{margin-top:14px;font-size:8.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--soft);
         text-align:center;border-top:1px solid var(--linha);padding-top:10px;line-height:1.8}}
</style>
<div class="doc">
  <div class="topo">
    <div><div class="marca">Lastro</div><div class="kicker">Certificado de saúde do equipamento</div></div>
    <div class="serie mono">SÉRIE <b>{serie}</b><br>{n_laudos} aferição(ões)<br>emitido sem conta</div>
  </div>
  <h1>{modelo}</h1>
  <div class="specs mono">{specs}</div>
  <div class="prog"><div class="rotulo mono">{prog_rotulo}</div><div class="valor">{prog_valor}</div><div class="sub">{prog_sub}</div></div>
  <table>{linhas_orgaos}</table>
  {historico}
  <div class="selo">
    <h3>Selo de verificação</h3>
    <dl class="mono">
      <dt>carimbo</dt><dd>{carimbo_em} · diário público Rekor (Linux Foundation)</dd>
      <dt>registro</dt><dd>{rekor_uuid_curto}… · índice {rekor_indice}</dd>
      <dt>laudo sha256</dt><dd>{laudo_sha_curto}…</dd>
      <dt>script</dt><dd>lastro-agent v{versao} · open source</dd>
    </dl>
    <div class="conferir">Recebeu este arquivo? Confira a autenticidade em
      <a href="{site}/conferir.html">{site_curto}/conferir.html</a>: arraste este arquivo lá.
      A página recalcula o hash e o compara com o registro público, sem depender de ninguém.</div>
  </div>
  <p class="micro">a data vem de um diário público append-only, não de quem emitiu · leitura feita por script
     open-source no próprio equipamento · nenhum número é digitado à mão · lastro · lastro · lastro</p>
</div>
<script type="application/json" id="lastro-prova">{prova_json}</script>
"""


def _gerar_certificado(laudo: dict, historico: list[dict], carimbo: dict,
                       laudo_bytes: bytes) -> pathlib.Path:
    import base64
    m = laudo["maquina"]
    specs = " · ".join(str(s) for s in [
        m.get("cpu") if m.get("cpu") not in (None, "desconhecido") else None,
        f"{m['ram_gb']} GB" if m.get("ram_gb") else None,
        f"SSD {m['armazenamento_gb']} GB" if m.get("armazenamento_gb") else None,
        m.get("so")] if s)
    nomes = {"ssd": "SSD (desgaste NAND)", "bateria": "Bateria",
             "memoria": "Memória (pressão)", "termico": "Térmico"}
    cores = {"saudavel": "ok", "atencao": "warn", "critico": "bad"}
    linhas = ""
    for org, dados in laudo["orgaos"].items():
        pct = round(dados["desgaste"] * 100)
        cru = dados.get("valor_cru") or f"{pct}% de desgaste"
        linhas += (f"<tr><td>{nomes.get(org, org)}<div class='medidor'>"
                   f"<i class='{cores[dados['estado']]}' style='width:{pct}%'></i></div></td>"
                   f"<td class='d'><span class='mono'>{cru} · {dados['estado']}</span></td></tr>")
    p = laudo.get("prognostico")
    if p:
        anos, meses = divmod(int(p["meses_restantes"]), 12)
        partes = ([f"{anos} ano{'s' * (anos != 1)}"] if anos else []) + \
                 ([f"{meses} mes{'es' * (meses != 1)}"] if meses or not anos else [])
        prog = ("prognóstico de vida útil restante", "≈ " + " e ".join(partes),
                f"gargalo: {p['gargalo']} · margem ±{p['margem_meses']} meses")
    else:
        prog = ("prognóstico", "primeira aferição",
                "re-afira em algumas semanas para medir a taxa de desgaste")
    historico_html = ""
    if len(historico) > 1:
        pontos = " · ".join(f"{l['aferido_em'][:10]}: {round(l['orgaos']['ssd']['desgaste']*100)}%"
                            for l in historico)
        historico_html = (f"<div class='specs mono' style='margin:0 0 14px'>caderneta (SSD): "
                          f"{pontos}</div>")
    prova = {"laudo_b64": base64.b64encode(laudo_bytes).decode(), "carimbo": carimbo}
    html = _CERT_MODELO.format(
        serie=laudo["serie"], n_laudos=len(historico), modelo=m["modelo"], specs=specs,
        prog_rotulo=prog[0], prog_valor=prog[1], prog_sub=prog[2],
        linhas_orgaos=linhas, historico=historico_html,
        carimbo_em=carimbo["integrado_em"], rekor_uuid_curto=carimbo["uuid"][:16],
        rekor_indice=carimbo["indice"], laudo_sha_curto=carimbo["sha256"][:16],
        versao=laudo["agente"]["versao"], site=SITE, site_curto=SITE.split("//")[1],
        prova_json=json.dumps(prova))
    destino = pathlib.Path.cwd()
    if not os.access(destino, os.W_OK):
        destino = pathlib.Path.home()
    arquivo = destino / f"lastro-certificado-{laudo['serie']}-{laudo['aferido_em'][:10]}.html"
    arquivo.write_text(html, encoding="utf-8")
    return arquivo


def emitir_sem_conta(laudo: dict) -> pathlib.Path:
    """Fluxo sem conta: caderneta local, prognostico, carimbo Rekor, certificado."""
    historico = _caderneta_local(laudo["serie"])
    prognostico = calcular_prognostico(laudo, historico)
    if prognostico:
        laudo["prognostico"] = prognostico
    (_dados_dir() / f"{laudo['aferido_em'][:10]}.json").write_text(
        _json_bonito(laudo), encoding="utf-8")
    historico = historico + [laudo]
    laudo_bytes = _json_bonito(laudo).encode("utf-8")
    print("    depositando o hash no diario publico (Rekor)...")
    carimbo = _carimbar_rekor(laudo_bytes)
    print(f"    carimbado: {carimbo['integrado_em']} · indice {carimbo['indice']}")
    return _gerar_certificado(laudo, historico, carimbo, laudo_bytes)


# ------------------------------------------------- um clique (GitHub via API)
# O fluxo do lastro.exe: le o hardware, autoriza no GitHub pelo Device Flow
# (codigo de 8 letras, sem senha, sem git instalado), cria o repositorio de
# passaporte do usuario se preciso e publica o laudo como UM commit via API.
# O commit continua sendo o carimbo; so muda quem digita.

CLIENT_ID = "Ov23liWw9JYNfAI8V5in"      # OAuth App "Lastro" (Device Flow); nao e segredo
REPO_PASSAPORTE = "lastro-passaporte"
SITE = "https://iosbilario.github.io/lastro"


def _api(url: str, token: str | None = None, dados: dict | None = None,
         metodo: str | None = None) -> dict:
    import urllib.error
    import urllib.request
    corpo = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(url, data=corpo,
                                 method=metodo or ("POST" if corpo else "GET"))
    req.add_header("Accept", "application/vnd.github+json"
                   if "api.github.com" in url else "application/json")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise LeituraError(f"GitHub respondeu {e.code} em {url}:\n"
                           f"{e.read().decode(errors='replace')[:300]}")
    except OSError as e:
        raise LeituraError(f"sem conexao com o GitHub ({e}). Verifique a rede e rode de novo.")


def _autorizar_github() -> str:
    """Device Flow: mostra um codigo, o usuario autoriza no navegador."""
    import time
    import webbrowser
    d = _api("https://github.com/login/device/code",
             dados={"client_id": CLIENT_ID, "scope": "public_repo"})
    if "user_code" not in d:
        raise LeituraError(f"nao consegui iniciar a autorizacao: {d}")
    print("\n=== autorizacao no GitHub ===")
    print(f"  1) vou abrir {d['verification_uri']} no seu navegador")
    print(f"  2) digite este codigo:  {d['user_code']}")
    print("  aguardando a autorizacao...")
    webbrowser.open(d["verification_uri"])
    intervalo = int(d.get("interval", 5))
    while True:
        time.sleep(intervalo)
        r = _api("https://github.com/login/oauth/access_token", dados={
            "client_id": CLIENT_ID, "device_code": d["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if "access_token" in r:
            print("  autorizado.")
            return r["access_token"]
        erro = r.get("error")
        if erro == "authorization_pending":
            continue
        if erro == "slow_down":
            intervalo += 5
            continue
        if erro == "expired_token":
            raise LeituraError("o codigo expirou antes da autorizacao. Rode de novo.")
        raise LeituraError(f"autorizacao nao concluida: {erro or r}")


def _historico_remoto(login: str) -> tuple[list[dict], dict]:
    """Laudos ja publicados no passaporte remoto (para prognostico e manifesto)."""
    import urllib.request
    raw = f"https://raw.githubusercontent.com/{login}/{REPO_PASSAPORTE}/main"

    def pega(caminho: str):
        try:
            with urllib.request.urlopen(f"{raw}/{caminho}", timeout=15) as r:
                return json.loads(r.read())
        except Exception:
            return None

    manifesto = pega("data/caderneta.json")
    if not manifesto or manifesto.get("sample"):
        manifesto = {"descricao": ("Indice da Caderneta, mantido pelo lastro-agent. "
                                   "O site descobre os laudos por aqui."),
                     "sample": False, "laudos": []}
        return [], manifesto
    laudos = []
    for nome in manifesto.get("laudos", []):
        l = pega(f"data/laudos/{nome}")
        if l:
            laudos.append(l)
    laudos.sort(key=lambda l: l["aferido_em"])
    return laudos, manifesto


def publicar_um_clique(laudo: dict, token: str) -> str:
    """Cria o repo de passaporte se preciso e publica o laudo como um commit."""
    import time
    login = _api("https://api.github.com/user", token)["login"]
    base = f"https://api.github.com/repos/{login}/{REPO_PASSAPORTE}"
    try:
        _api(base, token)
    except LeituraError:
        print(f"criando o seu repositorio de passaporte: {login}/{REPO_PASSAPORTE}")
        _api("https://api.github.com/user/repos", token, {
            "name": REPO_PASSAPORTE,
            "description": "Passaporte de saude do meu equipamento (Lastro).",
            "homepage": f"{SITE}/laudo.html?p={login}/{REPO_PASSAPORTE}",
            "auto_init": True})
        _api(f"{base}/topics", token, {"names": ["lastro-passaporte"]}, metodo="PUT")

    historico, manifesto = _historico_remoto(login)
    prognostico = calcular_prognostico(laudo, historico)
    if prognostico:
        laudo["prognostico"] = prognostico

    ref = None
    for _ in range(10):     # repo recem-criado pode demorar a expor o branch
        try:
            ref = _api(f"{base}/git/ref/heads/main", token)
            break
        except LeituraError:
            time.sleep(1.5)
    if not ref:
        raise LeituraError("o repositorio foi criado mas o branch main nao apareceu. Rode de novo.")

    pai = ref["object"]["sha"]
    arvore_pai = _api(f"{base}/git/commits/{pai}", token)["tree"]["sha"]
    nome = laudo["aferido_em"][:10] + ".json"
    if nome not in manifesto["laudos"]:
        manifesto["laudos"].append(nome)
        manifesto["laudos"].sort()
    arquivos = {
        f"data/laudos/{nome}": _json_bonito(laudo),
        "data/latest.json": _json_bonito(laudo),
        "data/caderneta.json": _json_bonito(manifesto),
    }
    arvore = _api(f"{base}/git/trees", token, {
        "base_tree": arvore_pai,
        "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c}
                 for p, c in arquivos.items()]})
    commit = _api(f"{base}/git/commits", token, {
        "message": f"laudo: afericao {laudo['aferido_em'][:10]} (serie {laudo['serie']})",
        "tree": arvore["sha"], "parents": [pai]})
    _api(f"{base}/git/refs/heads/main", token, {"sha": commit["sha"]}, metodo="PATCH")
    print(f"laudo publicado: commit {commit['sha'][:7]} em {login}/{REPO_PASSAPORTE}")
    _espera_ficar_publico(login)
    return f"{SITE}/laudo.html?p={login}/{REPO_PASSAPORTE}"


def _espera_ficar_publico(login: str):
    """Repo recem-criado demora alguns segundos para aparecer no raw (CDN).
    Espera o laudo responder antes de abrir o certificado, para o usuario
    nunca ver a pagina vazia."""
    import time
    import urllib.request
    url = f"https://raw.githubusercontent.com/{login}/{REPO_PASSAPORTE}/main/data/latest.json"
    print("    esperando o carimbo ficar publico...", end="", flush=True)
    for i in range(15):
        try:
            with urllib.request.urlopen(f"{url}?r={i}", timeout=10) as r:
                if r.status == 200:
                    print(" ok")
                    return
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(3)
    print("\n    o GitHub esta demorando; se o certificado abrir vazio, recarregue a pagina.")


def fluxo_um_clique() -> int:
    import webbrowser
    print("Lastro : passaporte de saude do equipamento")
    print("1/3 lendo o hardware desta maquina...")
    laudo = montar_laudo()
    ssd = laudo["orgaos"]["ssd"]
    print(f"    SSD: {ssd['valor_cru']} ({ssd['estado']})")

    print("\n2/3 como quer emitir?")
    print("  [1] certificado-arquivo, sem precisar de conta nenhuma (recomendado)")
    print("      carimbo em diario publico; voce anexa o arquivo no anuncio")
    print("  [2] link publico via GitHub (usa ou cria sua conta)")
    print("      passaporte vivo com historico na nuvem")
    try:
        escolha = input("  escolha [1]: ").strip() or "1"
    except EOFError:
        escolha = "1"

    if escolha == "2":
        print("\n3/3 autorizando no GitHub (nada e enviado sem isso)...")
        token = _autorizar_github()
        print("    publicando o laudo (o commit e o carimbo)...")
        url = publicar_um_clique(laudo, token)
        print(f"\npronto. Seu certificado:\n  {url}")
        print(f"  versao para o anuncio: {url}&certificado")
        webbrowser.open(url)
    else:
        print("\n3/3 emitindo o certificado (nenhuma conta, nenhum cadastro)...")
        arquivo = emitir_sem_conta(laudo)
        print(f"\npronto. Seu certificado esta em:\n  {arquivo}")
        print("  anexe este arquivo no anuncio; o comprador confere em "
              f"{SITE}/conferir.html")
        webbrowser.open(arquivo.as_uri())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="lastro-agent")
    p.add_argument("--emitir", action="store_true", help="gera e imprime o laudo")
    p.add_argument("--commit", action="store_true", help="grava o laudo na Caderneta e comita")
    p.add_argument("--um-clique", action="store_true",
                   help="fluxo completo via GitHub API (o que o lastro.exe roda)")
    args = p.parse_args(argv)

    if args.um_clique or (getattr(sys, "frozen", False) and not args.emitir):
        try:
            return fluxo_um_clique()
        except LeituraError as e:
            print(f"\nlastro-agent: parou sem publicar nada.\n{e}", file=sys.stderr)
            return 1
        finally:
            if getattr(sys, "frozen", False):
                try:
                    input("\npressione Enter para fechar")
                except EOFError:
                    pass

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
