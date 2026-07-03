#!/usr/bin/env python3
"""
lastro-agent : afere a saude do equipamento e emite um laudo.json.

Este e o UNICO componente que toca o hardware. O site (GitHub Pages) nunca le
hardware; ele so renderiza o laudo que este agente comita. E dai que nasce a
confianca do selo: o dado nasce local, o GitHub so carimba o commit.

Estado: SCAFFOLDING. Leituras triviais (modelo, RAM, SO) ja funcionam via psutil.
As leituras de desgaste (SSD/SMART, bateria) estao marcadas com TODO e hoje
retornam placeholders. O Claude Code deve implementar os leitores por plataforma.

Uso:
    python3 lastro_agent.py --emitir            # imprime o laudo no stdout
    python3 lastro_agent.py --emitir --commit    # emite e comita em data/laudos/

Observacoes de plataforma (o agente resolve isso, ver SPEC.md secao "Leitura"):
    - SSD NVMe: `smartctl -A -j /dev/nvmeN` -> campo "percentage_used". Costuma
      exigir sudo. Trate a ausencia de permissao com uma mensagem clara, nunca
      com um numero inventado.
    - Bateria: Linux /sys/class/power_supply, macOS `ioreg`, Windows
      `powercfg /batteryreport`.
    - Serie: hash estavel e ANONIMO de identificadores de hardware. Nunca gravar
      o serial de fabrica em claro.
"""
import argparse
import datetime as dt
import hashlib
import json
import platform
import subprocess
import sys

SCHEMA_VERSAO = "1"
AGENTE_VERSAO = "1.4.0"


def _sha256_de_mim() -> str:
    """sha256 do proprio arquivo, para proveniencia no laudo."""
    with open(__file__, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _serie_anonima() -> str:
    """
    Identificador estavel e anonimo da maquina.
    TODO(claude-code): derivar de (uuid da placa + modelo), passar por sha256,
    e formatar como BR-XX-XXXX. Jamais expor o serial de fabrica.
    """
    base = platform.node() + platform.machine()
    h = hashlib.sha256(base.encode()).hexdigest().upper()
    return f"BR-{h[:2]}-{h[2:6]}"


def ler_maquina() -> dict:
    """Leituras triviais. Isto ja funciona sem privilegio."""
    try:
        import psutil  # noqa
        ram_gb = round(psutil.virtual_memory().total / (1024 ** 3))
    except Exception:
        ram_gb = None
    return {
        "modelo": _modelo_placa() or platform.node(),
        "cpu": platform.processor() or "desconhecido",
        "ram_gb": ram_gb,
        "armazenamento_gb": None,  # TODO(claude-code): somar discos fisicos
        "so": f"{platform.system()} {platform.release()}",
        "comprado_em": None,       # opcional, informado pelo usuario em config
    }


def _modelo_placa():
    """TODO(claude-code): ler o modelo real por plataforma.
    Linux: /sys/class/dmi/id/product_name. macOS: system_profiler. Win: wmic csproduct.
    """
    try:
        with open("/sys/class/dmi/id/product_name") as f:
            return f.read().strip()
    except Exception:
        return None


def ler_ssd() -> dict:
    """
    Desgaste do SSD via SMART. ORGAO OBRIGATORIO.
    TODO(claude-code): chamar smartctl, parsear percentage_used (NVMe) ou
    wear_leveling_count (SATA), normalizar para 0..1. Se faltar permissao,
    levantar erro claro pedindo sudo. NUNCA retornar valor inventado.
    """
    # placeholder de scaffolding:
    desgaste = 0.62
    return {
        "desgaste": desgaste,
        "valor_cru": "Percentage Used: 62% (PLACEHOLDER)",
        "estado": _estado(desgaste, atencao=0.4, critico=0.6),
    }


def ler_bateria() -> dict | None:
    """TODO(claude-code): recargas + saude por plataforma. None se nao houver bateria."""
    desgaste = 0.412
    return {
        "desgaste": desgaste,
        "recargas": 412,
        "saude_pct": 89,
        "estado": _estado(desgaste, atencao=0.5, critico=0.8),
    }


def ler_memoria() -> dict:
    """Proxy de pressao: observa swap sob a carga atual."""
    try:
        import psutil
        sw = psutil.swap_memory()
        swap_frequente = sw.total > 0 and (sw.sin + sw.sout) > 0
        desgaste = 0.78 if swap_frequente else 0.2
    except Exception:
        swap_frequente, desgaste = True, 0.78
    return {"desgaste": desgaste, "swap_frequente": swap_frequente,
            "estado": _estado(desgaste, atencao=0.5, critico=0.85)}


def ler_termico() -> dict:
    """TODO(claude-code): detectar throttling termico sustentado."""
    desgaste = 0.22
    return {"desgaste": desgaste, "throttle": False,
            "estado": _estado(desgaste, atencao=0.6, critico=0.85)}


def _estado(d, atencao, critico):
    return "critico" if d >= critico else "atencao" if d >= atencao else "saudavel"


def montar_laudo() -> dict:
    laudo = {
        "versao": SCHEMA_VERSAO,
        "serie": _serie_anonima(),
        "maquina": ler_maquina(),
        "aferido_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "agente": {"nome": "lastro-agent", "versao": AGENTE_VERSAO, "sha256": _sha256_de_mim()},
        "orgaos": {
            "ssd": ler_ssd(),
            "bateria": ler_bateria(),
            "memoria": ler_memoria(),
            "termico": ler_termico(),
        },
    }
    # Prognostico local e opcional. O Observatorio refina depois.
    # TODO(claude-code): extrapolar a taxa de desgaste do proprio historico de commits.
    return laudo


def comitar(laudo: dict):
    """
    TODO(claude-code): gravar em data/laudos/AAAA-MM-DD.json, atualizar
    data/latest.json, e `git add/commit/push`. O commit e o carimbo temporal:
    e ele, e nao o campo aferido_em, que da a garantia inforjavel.
    """
    raise NotImplementedError("commit ainda nao implementado (ver SPEC.md).")


def main(argv=None):
    p = argparse.ArgumentParser(description="lastro-agent")
    p.add_argument("--emitir", action="store_true", help="gera e imprime o laudo")
    p.add_argument("--commit", action="store_true", help="comita o laudo no repo")
    args = p.parse_args(argv)

    if not args.emitir:
        p.print_help()
        return 0

    laudo = montar_laudo()
    print(json.dumps(laudo, ensure_ascii=False, indent=2))
    if args.commit:
        comitar(laudo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
