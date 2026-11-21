# Campanha 54 — medição final no conjunto de avaliação (missão 10, 21/11/2026, slot `avulso`)

Uma única rodada, com os funis exatamente como congelados em `finalistas54__dev.md` (nada foi mudado depois de olhar a avaliação). Conjunto `aval`: 2.964 eventos da pi-cam-001 (14/07 a 08/09/2026) nunca usados antes: 2.377 S0, 349 S1, 238 S2 (47 detecções confirmadas, 100 rejeitadas, 21 outras). O `pass` da avaliação (os que passam no filtro mais todos os confirmados) tem 839 eventos. Saída completa: `devil54__aval.txt` (`CAMP54_SPLIT=aval python devil54.py`).

## Resultado

| Funil (filtro + gate + detail) | Confirmadas | Rejeitadas | Alertas por 1.000 eventos [95%] | Parte S0 | Custo por evento, detail no Vertex [95%] |
|---|---|---|---|---|---|
| Controle: hoje refeito (2.5-flash-lite + 2.5-flash) | 32 de 47 (68%) | 50 de 100 | 16,7 [13,3 a 20,6] | 7,7 | −51% [−55 a −46] |
| **A: Nova Lite + 3.8-flash** | **30 de 47 (64%)** | **35 de 100** | **17,6 [13,7 a 21,9]** | 9,4 | −23% [−32 a −13]; com o preço medido no Vertex, cerca de −17% |
| **B: 3.1-flash-lite + 3.8-flash** | **37 de 47 (79%)** | **44 de 100** | **26,8 [21,7 a 32,4]** | 17,5 | −17% [−25 a −7]; com o preço medido no Vertex, cerca de −12% |

Desenvolvimento, para comparar: controle 21/32 e 26/61, 14,1 alertas; A 25/32 e 19/61, 15,9; B 25/32 e 23/61, 27,7.

## Diferenças pareadas (detecções; McNemar exato)

- Confirmadas, A × controle: 23 as duas, 7 só A, 9 só controle (A − controle = −2; p = 0,80): **empate**.
- Confirmadas, B × controle: 29, 8 só B, 3 só controle (+5; p = 0,23): B tende a mais, sem significância.
- Confirmadas, A × B: 29, 1 só A, 8 só B (−7; **p = 0,04**): **na avaliação o B mantém mais confirmadas que o A** (no desenvolvimento empatavam, 25 × 25).
- Rejeitadas, A × controle: 15 só A, 30 só controle (p = 0,04): o A deixa passar menos rejeitadas que hoje. B × controle: 22 × 28 (p = 0,48).
- Alertas por 1.000, A − controle: [−3,9 a +5,4] (empate); B − controle: [+4,5 a +15,6]; A − B: [−14,3 a −4,7] (A menor em 100% dos 2.000 sorteios). A sobra do B vem dos S0 (17,5 contra 9,4 do A e 7,7 do controle).

## Régua escrita antes (finalista ≥ controle − 2 nas confirmadas; custo ≤ hoje + 20%; rejeitadas ≤ controle)

- **A passa, no limite**: 30 ≥ 30; custo −23%; 35 ≤ 50.
- **B passa**: 37 ≥ 30; custo −17%; 44 ≤ 50.
- A régua é fraca (missão 9): barra desastre, não perda moderada. Por isso valem as diferenças pareadas acima.

## Por onde o A perde confirmadas

O gate. Com o filtro aplicado, o gate Nova Lite passa 33 das 47 confirmadas, o mesmo que o gate de hoje refeito (33), e o gate 3.1-flash-lite passa 43. O detail 3.8-flash é o mesmo nos dois e mantém 30 das 33 do A e 37 das 43 do B. No desenvolvimento os três gates passavam 28, 27 e 22 das 32 (conjunto `pass`, números do painel). O filtro barra 2 dos 72 eventos confirmados (2 detecções inteiras, que nenhum funil pode manter); no desenvolvimento não barrava nenhum.

## Detail no Vertex (pendência 11, aprovada às ~15:40)

`d38f_g3_low_low` no Vertex nos 58 eventos S2C em que o gate do A dispara (US$ 1,14; `detail54__d38f_g3_low_low_vtx__aval__r1.jsonl`). Concorda com o AI Studio em 54 de 57 eventos (50 e 49 "sim"); **as confirmadas mantidas pelo A são 30 nos dois**. Custo medido: US$ 0,0193 por chamada nesses eventos (o Vertex conta cerca de 870 tokens de entrada a mais que o AI Studio no mesmo evento, +8,8%); a tabela do custo usa os tokens do AI Studio a preço do Vertex, por isso a correção para cerca de −17% (A) e −12% (B). **Latência no Vertex, modo padrão, 3 em paralelo: p50 20,0 s, p90 46,8 s, máximo 345 s** (no AI Studio, modo padrão, 8 em paralelo: p50 13,4 s, p90 31,0 s). O `GEMINI_TIMEOUT_SECONDS` de produção é 45 s; o rollout pede 90 s. S2R e S1 não foram medidos no Vertex (verba).

## Latência dos gates

Nova Lite no Bedrock, p90 6,1 s (desenvolvimento 4,0 s; corte do gate em produção 15 s). Os gates Gemini rodaram em Flex na avaliação, como no desenvolvimento: latência em modo padrão não medida aqui (3,0 s no painel para o 3.1-flash-lite).

## Gasto

AI Studio cerca de US$ 6,6 da cota de US$ 7,00 (filtro 0,48 mais cerca de 0,03 de chamadas duplicadas por um minuto, quando reiniciei o filtro com mais paralelismo; gates 0,42 e 0,37; detail 3.8-flash 3,84; detail de hoje 1,46). Bedrock US$ 0,28. Vertex US$ 1,14 dos 1,46 aprovados. Tráfego da AWS da busca das janelas: cerca de US$ 0,05.

## Diferenças conhecidas entre o teste e a produção (valem para todos os números)

As da missão 4 e da missão 9: replay na API do AI Studio (o Vertex responde diferente em parte dos eventos; aqui, no detail 3.8-flash nos S2C, 3 de 57); o aviso da janela anterior é reconstituído pela contagem de tokens; o gate de hoje refeito não repete todas as decisões de produção (a produção passa as 47 confirmadas por definição; o replay, 33); os S0 não têm rótulo do operador; uma câmera e um período.

## Alertas em cenas sem disparo em produção (S0), lidos a olho

Os 51 S0 em que o detail 3.8-flash confirma depois do gate do A ou do B foram lidos em folhas da janela (`s0_sim__aval54__revisao.tsv`; folhas de `make_sheets_window54.py`). Um revisor só (o agente), **sem cegamento** (a legenda da folha dizia o grupo), como na missão 6. Cada S0 confirmado vale 0,41 alerta por 1.000 eventos.

| Grupo | Eventos | Descarte provável | Falso provável | Indefinido |
|---|---|---|---|---|
| Só B | 28 | 6 | 16 | 6 |
| Só A | 8 | 2 | 3 | 3 |
| Os dois | 15 | 3 | 7 | 5 |
| **Total A** | 23 | 5 | 10 | 8 |
| **Total B** | 43 | 9 | 23 | 11 |

Em alertas por 1.000: falsos prováveis A 4,1 (7,3 se os indefinidos forem falsos), B 9,4 (13,8); descartes novos A 2,0 a 5,3, B 3,7 a 8,1. Os falsos do B são sobretudo catadores com carrinho ou bag, pessoas revirando a pilha à noite e objetos postos no latão. À noite o B confirma 12 S0, dos quais 8 parecem falsos (no desenvolvimento, 9 de 12). Dos 19 S0 que o controle confirma, só os 8 em comum com A ou B foram lidos.

## Leitura

- **A**: empata com hoje refeito em confirmadas (30 × 32, p = 0,80) e em alertas (17,6 × 16,7), deixa passar menos rejeitadas (35 × 50, p = 0,04) e custa cerca de 17% a 23% menos que hoje. Passa na régua no limite. O ganho de confirmadas que o desenvolvimento sugeria (25 × 21) não se repetiu: é empate.
- **B**: mantém mais confirmadas que o A (37 × 30, 8 × 1 nos pares, p = 0,04) e tende a mais que hoje (37 × 32, p = 0,23), ao preço de cerca de 10 alertas a mais por 1.000 eventos, dos quais a maior parte parece falsa pela leitura a olho (catador, latão, noite).
- **A escolha entre A e B é de negócio**: detectar mais (B) ou não aumentar os alertas falsos (A). Pela regra escrita (sem aumentar os alertas falsos), o A continua sendo o que cumpre; o B é o que mais se aproxima da meta de 90% das confirmadas (79% contra 64% e 68%, sempre contra a produção, que por definição passa as 47).
- Nenhum dos três chega a 90% das confirmadas de produção no replay (nem o próprio gate de hoje refeito: 68%); a diferença é do replay (gate não determinístico perto do limiar, plataforma), não só dos candidatos.
