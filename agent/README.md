# lastro-agent

O unico componente que le o hardware. Roda uma vez (ou periodicamente), gera um
`laudo.json` e o comita no seu repositorio de passaporte. O site nunca le
hardware, so renderiza o commit. E dai que vem a confianca do selo.

## Rodar

```bash
pip install -r requirements.txt
sudo apt install smartmontools        # ou brew/choco, ver requirements.txt
python3 lastro_agent.py --emitir      # imprime o laudo
python3 lastro_agent.py --emitir --commit   # emite e comita (quando implementado)
```

## Por que sudo

A leitura de desgaste do SSD (SMART) quase sempre exige privilegio. Se faltar
permissao, o agente deve dizer isso de forma clara e parar, nunca inventar um
numero. Um laudo so vale se cada valor veio de verdade do hardware.

## Estado

Scaffolding. As leituras de modelo, RAM, SO e swap ja funcionam via psutil.
As leituras de desgaste (SSD/SMART, bateria) estao marcadas com TODO. Ver
`../SPEC.md`, secao "Leitura", para o que implementar por plataforma.
