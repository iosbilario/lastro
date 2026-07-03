# SPEC : Lastro

Especificacao de produto e tecnica. Fonte de verdade para o Claude Code.

## 1. Usuario e job

Usuaria concreta: Ana, designer autonoma em Sao Paulo, notebook Dell de 2019
ficando lento. Job: "descobrir se aguenta mais dois anos ou se troco, e, se eu
vender, provar que a maquina e honesta, sem depender de uma loja que so quer me
empurrar uma nova".

O produto nao empurra maquina nova. Vies deliberado: no Brasil, importar hardware
custa 2x a 3x, entao a decisao economica quase sempre e estender a vida com o
upgrade certo, nao substituir.

## 2. Core loop

    afere -> laudo comitado (carimbo do GitHub) -> re-afere de tempos em tempos
    -> historico de commits vira a curva -> link publico vira o certificado
    -> cada afericao alimenta o Observatorio -> prognostico de todos melhora

O que compoe: cada re-afericao deixa o SEU passaporte mais valioso (historico mais
longo = mais confianca + prognostico melhor) E melhora o modelo coletivo. Efeito
de rede de dados.

## 3. Modelo de dominio

- **Maquina / Passaporte** : identidade anonima estavel (serie) + o repo publico.
- **Laudo** : uma afericao. Um commit. Conforme `site/laudo.schema.json`.
- **Orgao** : SSD, bateria, memoria, termico. Valor cru + desgaste 0..1 + estado.
- **Caderneta** : a sequencia de laudos = a curva de desgaste no tempo.
- **Prognostico** : meses restantes, derivado da taxa de desgaste do gargalo,
  refinado pela curva da frota no Observatorio.
- **Selo** : a verificacao. Timestamp do commit + sha256 do agente. Inforjavel.
- **Observatorio** : agregado por modelo (amostra, desgaste mediano/mes, percentis).

## 4. Arquitetura (100% GitHub, zero servidor)

    [ lastro-agent (local) ] --commit--> [ repo do passaporte do usuario ]
                                                | topic: lastro-passaporte
                                                v
    [ Action noturna no repo central ] --Search API--> encontra todos os passaportes
                                                | le cada latest.json, anonimiza, agrega
                                                v
                                         data/observatorio.json --> [ GitHub Pages ]

Decisao: cada usuario tem o proprio repo de passaporte (ou gist), para que o
commit e o timestamp fiquem na conta dele. O repo central hospeda o site, o
agregador e a distribuicao do agente. Descoberta pela topic `lastro-passaporte`.

## 5. Leitura (o que o agente implementa por plataforma)

Regra de ouro: se nao der para ler de verdade, o agente PARA com mensagem clara.
Nunca inventa um numero. Um laudo so vale se cada valor veio do hardware.

- **SSD (obrigatorio)** : `smartctl -A -j`. NVMe -> `percentage_used`. SATA ->
  `wear_leveling_count` normalizado. Costuma exigir sudo; tratar EPERM com
  instrucao, nao com placeholder.
- **Bateria** : recargas + saude. Linux `/sys/class/power_supply/BAT*`,
  macOS `ioreg -r -c AppleSmartBattery`, Windows `powercfg /batteryreport`.
- **Memoria** : pressao real via swap sob carga (psutil).
- **Termico** : throttling sustentado (opcional no v1).
- **Serie** : hash estavel e anonimo de identificadores de placa. Formato
  `BR-XX-XXXX`. Nunca gravar serial de fabrica em claro.

## 6. Prognostico (v1 transparente, nada de caixa-preta)

1. Da Caderneta, calcular a taxa de desgaste do gargalo (ex.: SSD +1.05%/mes).
2. Meses restantes = (1 - desgaste_atual) / taxa.
3. Gargalo = orgao que atinge fim de vida primeiro.
4. Se houver Observatorio para o modelo, usar a taxa mediana da frota como priori
   quando o historico local for curto (menos de 3 laudos).
5. Sempre expor margem e base amostral. Estimativa honesta, com incerteza a mostra.

## 7. Verificacao / selo

- v1: proveniencia por commit publico (timestamp inforjavel) + sha256 do agente
  registrado no laudo. O verificador confere que o sha bate com uma release
  conhecida do agente.
- v2 (endurecimento): assinar commits com sigstore/gitsign para prova
  criptografica de autoria, nao so de tempo.

## 8. Privacidade

- Nada de PII. Serie e hash anonimo. Serial de fabrica jamais em claro.
- O Observatorio so guarda agregados por modelo, nunca a serie individual.
- O usuario decide tornar o passaporte publico (e o que o certificado exige).

## 9. Milestones (ordem sugerida)

- **M0** : validar o schema; validador de laudo verde no CI.
- **M1 (Caderneta local)** : agente le SSD real (uma plataforma, ex. Linux),
  emite e comita; site renderiza o passaporte a partir do commit, portando o
  visual de `design/lastro-passaporte.html`.
- **M2 (Certificado)** : link publico do passaporte + selo com hash e timestamp;
  botao "copiar link".
- **M3 (Observatorio)** : Action noturna agrega pela topic; site mostra "onde
  voce esta" na curva da frota.
- **M4 (multiplataforma)** : leitores de macOS e Windows; distribuicao do agente.
- **M5 (endurecimento)** : gitsign; prognostico usando priori da frota.

## 10. Nao objetivos (v1)

- Nada de conta, login ou servidor.
- Nada de recomendacao de compra de maquina nova (o vies e o oposto).
- Nada de coleta de dado que saia sem o commit explicito do usuario.
