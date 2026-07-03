#!/usr/bin/env python3
"""
Registra a release atual do agente em agent/releases.json.

O laudo carrega o sha256 do script que o gerou. O validador (em laudos reais)
e o selo do site conferem esse sha contra esta lista: e assim que o comprador
sabe que o laudo saiu do script open-source oficial, nao de um arquivo editado
a mao. Rode este script a cada mudanca no agente, no mesmo commit.
"""
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
AGENTE = RAIZ / "agent" / "lastro_agent.py"
RELEASES = RAIZ / "agent" / "releases.json"


def main() -> int:
    codigo = AGENTE.read_bytes().replace(b"\r\n", b"\n")  # hash independente de checkout
    sha = hashlib.sha256(codigo).hexdigest()
    versao = re.search(r'AGENTE_VERSAO\s*=\s*"([^"]+)"', codigo.decode("utf-8"))
    if not versao:
        print("nao achei AGENTE_VERSAO no agente", file=sys.stderr)
        return 1

    try:
        registro = json.loads(RELEASES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        registro = {
            "descricao": ("Releases conhecidas do lastro-agent. Um laudo real so e "
                          "verificavel se o sha256 do agente que o gerou estiver aqui."),
            "releases": {},
        }

    if sha in registro["releases"]:
        print(f"ja registrado: {sha[:12]}… (v{registro['releases'][sha]['versao']})")
        return 0

    registro["releases"][sha] = {
        "versao": versao.group(1),
        "registrado_em": dt.date.today().isoformat(),
    }
    RELEASES.write_text(json.dumps(registro, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"registrado: v{versao.group(1)} · sha256 {sha[:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
