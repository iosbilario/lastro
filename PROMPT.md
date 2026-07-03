# Prompt de arranque (cole no Claude Code)

Copie o bloco abaixo na primeira mensagem para o Claude Code, com este
repositorio aberto como diretorio de trabalho.

---

Voce vai construir o **Lastro**: o passaporte de saude de um equipamento,
hospedado 100% no GitHub (sem servidor, sem banco de dados, sem custo). Todo o
contexto ja esta no repo. Leia, nesta ordem, antes de escrever qualquer codigo:
`README.md` (conceito), `SPEC.md` (dominio, arquitetura, milestones, leitura por
plataforma), `CLAUDE.md` (convencoes e guardrails) e abra
`design/lastro-passaporte.html` no navegador: e a fonte de verdade visual, para
portar, nao redesenhar.

A ideia em uma frase: um mesmo `laudo.json`, comitado no GitHub, e ao mesmo tempo
o certificado que o dono mostra pra vender a maquina, a caderneta de desgaste dele
(o historico de commits e a serie temporal) e uma linha do Observatorio coletivo
que uma Action agrega. O commit do GitHub e o carimbo de cartorio: inforjavel e
neutro. Essa e a razao de ser 100% GitHub.

Regras que nao se quebram (detalhe em `CLAUDE.md`):
- Zero servidor. Se algo pedir backend, ache o caminho GitHub-nativo (Pages,
  Actions, Search API, git como banco temporal).
- So o agente toca hardware; o site apenas renderiza o commit.
- Nunca inventar um numero: leitura que falha para com mensagem clara.
- Prognostico transparente; privacidade por hash anonimo; sem PII.

Comece assim:

1. **Confirme o entendimento** em 5 linhas: o core loop, por que 100% GitHub e o
   wedge, e onde as tres funcoes (certificado, caderneta, observatorio) vivem no
   mesmo artefato. Se algo no SPEC estiver ambiguo, pergunte antes de codar.

2. **Proponha o plano do M1** (a Caderneta local, ver SPEC secao 9) como uma
   lista de commits pequenos. Nao ataque tudo de uma vez.

3. **Execute o M1**, comitando passo a passo:
   - Implemente o validador de schema (`validate-laudo.yml` + script) e deixe o
     CI verde sobre os laudos de exemplo em `data/laudos/`.
   - Implemente a leitura real do SSD via smartctl no `lastro_agent.py` para uma
     plataforma (comece por Linux). Trate falta de sudo com instrucao, sem
     placeholder. Implemente `--commit`.
   - Porte o visual de `design/lastro-passaporte.html` para `site/index.html`,
     ligando cada campo a `data/latest.json` e a Caderneta a `data/laudos/`.
     Deixe a sparkline e o selo funcionando com dado real.

4. Ao fim do M1, rode tudo numa passada limpa seguindo o `agent/README.md`,
   mostre o resultado e so entao proponha o M2.

Trabalhe incremental, explique cada decisao de arquitetura em uma linha, e me
mostre o diff antes de commits grandes. Pode comecar pelo passo 1.
