# Lastro

O passaporte de saude do seu equipamento. Um laudo publico, datado e inforjavel,
hospedado inteiramente no GitHub. Sem servidor, sem banco de dados, sem custo.

Site publicado: https://iosbilario.github.io/lastro/ (landing -> verificador ->
certificado). O passaporte vive em `laudo.html`, com dados de exemplo ate a
primeira afericao real; o link com `laudo.html?certificado` e a visao do comprador.

A palavra vem do mercado: *lastro* e a garantia que sustenta um valor. Aqui, o
historico de saude da maquina e o lastro que sustenta o quanto ela vale de
segunda mao e a sua decisao de mante-la viva mais tempo.

## Tres funcoes, um so artefato

O mesmo `laudo.json`, comitado no GitHub, serve a tres propositos ao mesmo tempo:

1. **Certificado (para o comprador).** O link publico, com carimbo temporal do
   commit, prova ao comprador de um usado que a maquina e honesta. Resolve o
   mercado dos limoes: quem vende algo bom finalmente consegue provar.
2. **Caderneta (para o dono).** Cada re-afericao e um commit. O historico de
   commits vira a curva de desgaste. A maquina passa a ter hodometro.
3. **Observatorio (o ativo coletivo).** Uma Action noturna agrega todos os
   passaportes publicos numa curva de mortalidade por modelo. Quanto mais gente
   afere, melhor o prognostico de todo mundo.

## Por que 100% GitHub e o pulo do gato

Nao e economia de infra, e o mecanismo de confianca. O GitHub vira:

- **Cartorio**: o timestamp do commit e neutro e inforjavel. Ninguem precisa
  confiar em nos, so no carimbo.
- **Banco de dados temporal**: o historico de commits do laudo e a serie
  temporal. (Mesmo padrao do Observatorio de Taxas.)
- **Camada de descoberta**: passaportes se anunciam com a topic
  `lastro-passaporte`; a Action os encontra pela Search API.
- **Compute**: Actions como cron; Pages como frontend.

## A fronteira honesta

Um site no navegador nao le SMART, ciclos de bateria nem desgaste real. Entao
quem le e o `lastro-agent`: um script open-source que roda uma vez na maquina,
gera o laudo e o comita. O site so renderiza o commit. E exatamente essa
separacao que torna o selo verificavel: o dado nasce local, o GitHub carimba.

## Mapa do repo

    design/lastro-passaporte.html   fonte de verdade VISUAL (o laudo, ja desenhado)
    site/                           GitHub Pages: renderiza o laudo a partir do JSON
    site/laudo.schema.json          o contrato do laudo (amarra tudo)
    agent/lastro_agent.py           le o hardware, emite e comita o laudo
    data/laudos/*.json              a Caderneta (o historico = o banco temporal)
    data/caderneta.json             indice da Caderneta (o site descobre os laudos por aqui)
    data/observatorio.json          saida do agregador
    .github/workflows/              agregador noturno + validador de schema

Para construir a partir daqui, leia `SPEC.md` e siga `PROMPT.md`.
