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
RELEASES = RAIZ / "agent" / "releases.json"

# (arquivo, regex da versao, nome do artefato ou None para o script python)
ARTEFATOS = [
    (RAIZ / "agent" / "lastro_agent.py", r'AGENTE_VERSAO\s*=\s*"([^"]+)"', None),
    (RAIZ / "site" / "go.ps1", r'\$VERSAO\s*=\s*"([^"]+)"', "go.ps1"),
]


def main() -> int:
    try:
        registro = json.loads(RELEASES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        registro = {
            "descricao": ("Releases conhecidas do lastro-agent. Um laudo real so e "
                          "verificavel se o sha256 do agente que o gerou estiver aqui."),
            "releases": {},
        }

    for arquivo, padrao, artefato in ARTEFATOS:
        if not arquivo.exists():
            continue
        codigo = arquivo.read_bytes().replace(b"\r\n", b"\n")  # hash independente de checkout
        sha = hashlib.sha256(codigo).hexdigest()
        versao = re.search(padrao, codigo.decode("utf-8"))
        if not versao:
            print(f"nao achei a versao em {arquivo.name}", file=sys.stderr)
            return 1
        if sha in registro["releases"]:
            print(f"ja registrado: {arquivo.name} {sha[:12]}… (v{registro['releases'][sha]['versao']})")
            continue
        entrada = {"versao": versao.group(1), "registrado_em": dt.date.today().isoformat()}
        if artefato:
            entrada["artefato"] = artefato
        registro["releases"][sha] = entrada
        print(f"registrado: {arquivo.name} v{versao.group(1)} · sha256 {sha[:12]}…")

    RELEASES.write_text(json.dumps(registro, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
