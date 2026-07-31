# Shadow Gemini-3.1 vs prod 2.5 — pi-cam-001

Ledger: 4132 eventos, 2026-07-22 a 2026-07-30. Rótulos do operador: 61 detecções exportadas.

> As duas fases NÃO são agregadas. `g3` troca modelo **e** prompt; só `current` isola o modelo, que é a pergunta da migração de 16/out.

### Fase `current`

- eventos: **1573** · gate disparou 11/1573 · 0.7% · detail rodou 11
- prod criou detecção: 18/1573 · 1.1% · shadow confirmaria: 10/1573 · 0.6%
- custo do shadow (recomputado dos tokens): **US$ 1.6819** (US$ 0.00107/evento)

| | shadow SIM | shadow NÃO |
|---|---|---|
| **prod SIM** | 5 | 13 |
| **prod NÃO** | 5 | 1550 |

Contra o operador (n=13 detecções julgadas):

- **recall** — de 2 CONFIRMADO, o 3.1 confirmaria 1/2 · 50.0%
- **alarme falso** — de 11 REJEITADO, o 3.1 confirmaria 4/11 · 36.4%

Discordâncias: **18** (5 SHADOW-ONLY sem rótulo, 13 PROD-ONLY) — ver `shadow_3v1_quadrants.csv`.

### Fase `g3`

- eventos: **2559** · gate disparou 287/2559 · 11.2% · detail rodou 287
- prod criou detecção: 59/2559 · 2.3% · shadow confirmaria: 213/2559 · 8.3%
- custo do shadow (recomputado dos tokens): **US$ 3.5754** (US$ 0.00140/evento)

| | shadow SIM | shadow NÃO |
|---|---|---|
| **prod SIM** | 43 | 16 |
| **prod NÃO** | 170 | 2330 |

Contra o operador (n=51 detecções julgadas):

- **recall** — de 32 CONFIRMADO, o 3.1 confirmaria 22/32 · 68.8%
- **alarme falso** — de 19 REJEITADO, o 3.1 confirmaria 15/19 · 78.9%

Discordâncias: **186** (170 SHADOW-ONLY sem rótulo, 16 PROD-ONLY) — ver `shadow_3v1_quadrants.csv`.

## Custo real (gemini_call_log)

| lado | estágio | chamadas | custo US$ | latência média | erros |
|---|---|---|---|---|---|
| prod (2.5) | detail | 171 | 1.6277 | 15938 ms | 2 |
| prod (2.5) | gate | 4743 | 4.6955 | 7819 ms | 113 |
| shadow (3.1) | detail | 298 | 0.7544 | 7919 ms | 0 |
| shadow (3.1) | gate | 4138 | 4.5101 | 4711 ms | 0 |

Total por lado: **prod (2.5)** US$ 6.3232 · **shadow (3.1)** US$ 5.2645.

## Arquivos

- `shadow_3v1.csv` — uma linha por evento do shadow, com o rótulo do operador
- `shadow_3v1_quadrants.csv` — só as discordâncias, para revisão manual
