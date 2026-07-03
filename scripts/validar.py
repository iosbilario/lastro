#!/usr/bin/env python3
"""
Valida laudos contra site/laudo.schema.json. Um laudo malformado nunca entra
na Caderneta: este script e a porta de entrada, rodado pelo CI a cada push.

Uso:
    python scripts/validar.py                    # valida data/laudos/*.json + data/latest.json
    python scripts/validar.py caminho1.json ...  # valida so os arquivos passados

Sai com codigo 1 se qualquer laudo falhar, listando cada erro com o caminho
do campo. Alem do schema, verifica coerencia interna: estado condizente com o
desgaste nao e checado (limiar e decisao do agente), mas datas devem ser
parseaveis e a serie deve ser igual em todos os laudos da mesma caderneta.
"""
import json
import pathlib
import sys

from jsonschema import Draft7Validator, FormatChecker

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = RAIZ / "site" / "laudo.schema.json"


def carregar_schema() -> Draft7Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema, format_checker=FormatChecker())


def validar_arquivo(caminho: pathlib.Path, validador: Draft7Validator) -> list[str]:
    """Retorna a lista de erros (vazia = valido)."""
    try:
        laudo = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"JSON invalido: {e}"]
    erros = []
    for erro in sorted(validador.iter_errors(laudo), key=lambda e: list(e.path)):
        onde = "/".join(str(p) for p in erro.path) or "(raiz)"
        erros.append(f"{onde}: {erro.message}")
    return erros


def alvos_padrao() -> list[pathlib.Path]:
    laudos = sorted((RAIZ / "data" / "laudos").glob("*.json"))
    latest = RAIZ / "data" / "latest.json"
    return laudos + ([latest] if latest.exists() else [])


def _checar_releases(alvos: list[pathlib.Path]) -> int:
    try:
        manifesto = json.loads((RAIZ / "data" / "caderneta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if manifesto.get("sample", True):
        return 0  # dados de exemplo nao tem proveniencia para conferir
    try:
        conhecidas = json.loads((RAIZ / "agent" / "releases.json").read_text(encoding="utf-8"))["releases"]
    except (OSError, json.JSONDecodeError, KeyError):
        print("FALHOU  caderneta real sem agent/releases.json para conferir proveniencia")
        return 1
    falhas = 0
    for caminho in alvos:
        try:
            laudo = json.loads(caminho.read_text(encoding="utf-8"))
            sha = laudo["agente"]["sha256"]
        except Exception:
            continue  # ja reprovado pelo schema
        if sha not in conhecidas:
            falhas += 1
            print(f"FALHOU  {caminho.name}: sha256 do agente ({sha[:12]}…) nao e uma "
                  "release conhecida; laudo pode ter sido editado a mao")
    return falhas


def main(argv: list[str]) -> int:
    validador = carregar_schema()
    alvos = [pathlib.Path(a) for a in argv] if argv else alvos_padrao()
    if not alvos:
        print("nenhum laudo para validar")
        return 0

    falhas = 0
    series = {}
    for caminho in alvos:
        erros = validar_arquivo(caminho, validador)
        rel = caminho.resolve()
        try:
            rel = rel.relative_to(RAIZ)
        except ValueError:
            pass
        if erros:
            falhas += 1
            print(f"FALHOU  {rel}")
            for e in erros:
                print(f"        {e}")
        else:
            print(f"ok      {rel}")
            try:
                series[str(rel)] = json.loads(caminho.read_text(encoding="utf-8"))["serie"]
            except Exception:
                pass

    # Coerencia da caderneta: todos os laudos validos devem ser da mesma maquina.
    if len(set(series.values())) > 1:
        falhas += 1
        print("FALHOU  caderneta com series distintas na mesma pasta:")
        for arq, s in series.items():
            print(f"        {arq}: {s}")

    # Proveniencia: em caderneta real (sample=false), o sha256 do agente de cada
    # laudo precisa ser uma release conhecida. E o que barra laudo editado a mao.
    falhas += _checar_releases(alvos)

    if falhas:
        print(f"\n{falhas} problema(s). Laudo malformado nao entra na Caderneta.")
        return 1
    print(f"\n{len(alvos)} laudo(s) validos.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
