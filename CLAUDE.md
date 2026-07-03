# CLAUDE.md : convencoes para o agente de codigo

Contexto vive em `README.md` (conceito) e `SPEC.md` (dominio, arquitetura,
milestones). O visual aprovado esta em `design/lastro-passaporte.html`: e a
fonte de verdade de pixel, nao reinvente o design, porte-o.

## Principios inegociaveis

1. **100% GitHub, zero servidor.** Sem backend, sem DB, sem infra paga. Tudo e
   JSON estatico versionado + Actions + Pages. Se uma solucao exigir servidor,
   ela esta errada; ache o caminho GitHub-nativo.
2. **O agente e o unico que toca hardware.** O site nunca le hardware, so
   renderiza o commit. Nao quebre essa fronteira: e ela que torna o selo
   confiavel.
3. **Nunca invente um numero.** Se uma leitura de hardware falhar (falta sudo,
   plataforma sem suporte), pare com mensagem clara. Um laudo com valor forjado
   destroi o produto inteiro.
4. **Prognostico transparente.** Formula legivel, incerteza sempre a mostra.
   Nada de caixa-preta.
5. **Privacidade.** Serie e hash anonimo. Serial de fabrica jamais em claro. O
   Observatorio so guarda agregados por modelo.

## Estilo

- Portugues nos textos de produto e comentarios. Sem travessao (use virgula,
  dois-pontos ou parenteses). Evite a palavra "ciclo" como muleta; para bateria,
  "recargas" ja resolve.
- Codigo: Python 3.12 no agente e nos scripts de Action. JS vanilla no site (sem
  framework, sem build step, coerente com o zero-infra). Sem dependencia que
  exija servidor.
- Commits pequenos e legiveis, um por passo do milestone.

## Definicao de pronto (por milestone)

Um milestone so fecha quando: o CI passa, roda de verdade numa maquina limpa
seguindo o README, e o valor exibido ao usuario veio de dado real (ou de sample
claramente rotulado como sample).

## Cuidados

- CSS do site: cuidado com especificidade ao portar o mockup (seletores de
  secao/elemento se cancelam em padding/margin). Ver `design/`.
- Sample vs real: os arquivos em `data/laudos/*.json` sao EXEMPLOS para o site ter
  o que renderizar. Ao ligar o agente real, deixe claro no UI quando o dado e
  sample.
