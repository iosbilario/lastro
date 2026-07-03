# lastro-agent

O unico componente que le o hardware. Roda uma vez (ou periodicamente), gera um
`laudo.json` e o comita no seu repositorio de passaporte. O site nunca le
hardware, so renderiza o commit. E dai que vem a confianca do selo.

## Um clique (Windows, para quem nao e dev)

Baixe o `lastro.exe` na release mais recente e de dois cliques. Ele pede a
permissao de administrador (UAC), le o hardware, autoriza no GitHub pelo
Device Flow (um codigo de 8 letras, sem senha), cria o repositorio
`lastro-passaporte` na sua conta se preciso e publica o laudo como um commit
via API. Sem git, sem terminal. O mesmo fluxo existe como
`python lastro_agent.py --um-clique`.

O exe embute o `smartctl` do smartmontools (GPL; fonte em
https://github.com/smartmontools/smartmontools) e seu sha256 fica registrado
em `releases.json`, como o do script.

## Rodar no terminal (Linux, a plataforma original do v1)

```bash
pip install -r requirements.txt
sudo apt install smartmontools

# so imprimir o laudo, sem gravar nada:
sudo python3 agent/lastro_agent.py --emitir

# emitir, gravar na Caderneta e comitar (o commit e o carimbo):
sudo python3 agent/lastro_agent.py --emitir --commit
```

Na primeira afericao real, o agente remove os laudos de exemplo da Caderneta
(eles sao de outra maquina) e o site deixa de mostrar a faixa de DADOS DE
EXEMPLO. Depois do `git push`, o carimbo temporal do GitHub passa a valer como
prova publica.

## Por que sudo

A leitura de desgaste do SSD (SMART) quase sempre exige privilegio. Se faltar
permissao, o agente diz isso e para, nunca inventa um numero. Um laudo so vale
se cada valor veio de verdade do hardware.

## O que e lido, por plataforma

| Orgao    | Linux                                   | Outras plataformas       |
|----------|-----------------------------------------|--------------------------|
| SSD      | `smartctl -A -j` (NVMe ou ATA)          | funciona onde houver smartmontools; sem ele, o agente para |
| Bateria  | `/sys/class/power_supply/BAT*`          | omitida no v1            |
| Memoria  | psutil (RAM ocupada + swap desde o boot)| psutil, igual            |
| Termico  | fora do v1                              | fora do v1               |

Orgao sem leitor na plataforma e OMITIDO do laudo. O SSD e obrigatorio: sem
leitura real de SMART nao existe laudo.

## Prognostico

Formula transparente, calculada da propria Caderneta (2+ afericoes reais):
taxa do orgao = variacao de desgaste / meses; meses restantes =
(1 - desgaste) / taxa; o gargalo e o orgao que zera primeiro; margem de 20%.
Sem historico, o campo simplesmente nao existe no laudo.

## Privacidade

A serie (`BR-XX-XXXX`) e um sha256 de identificadores de placa: estavel para a
mesma maquina, irreversivel para quem le. Nenhum serial de fabrica sai em claro.
