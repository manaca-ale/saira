# Revisão cética da missão 11 (22/11/2026, slot `noiteB`, sem custo de API)

Conferidos, contra `results/final54__aval.md`, `results/devil54__aval.txt` e os jsonl `__aval`, os números da seção "Resultado final" da página (Claude Docs, revisão 15) e do `ROLLOUT-2027-01.md`.

## Batem (recontados nos arquivos)

| Afirmação | Fonte | Recontagem |
|---|---|---|
| Confirmadas 32 / 30 / 37 de 47; rejeitadas 50 / 35 / 44 de 100 | devil54 seção 1 | igual |
| Alertas por 1.000 16,7 / 17,6 / 26,8 e faixas de 95% | devil54 seção 4 | igual |
| Custo −51% / −23% / −17%; com o preço do Vertex cerca de −17% e −12% | devil54 seção 4; final54 | igual |
| Pares: A × hoje 7 × 9 (p = 0,80); A × B 1 × 8 (p = 0,04); rejeitadas A × hoje 15 × 30 (p = 0,04) | devil54 seção 2 | igual |
| Gate passa 33 / 33 / 43 das 47 confirmadas (com o filtro) | jsonl dos três gates | 33 / 33 / 43 |
| Margem de 30 de 47: 50% a 76% | devil54 seção 2 (Wilson) | igual |
| Detail no Vertex: 8 de 58 acima de 45 s, 1 acima de 90 s; US$ 0,0193 por chamada; 54 de 57 iguais ao AI Studio; 30 confirmadas | jsonl `_vtx` (61 linhas: 58 válidas, 3 paradas pela trava); devil54 seção 8 | igual; p50 19,9 s e p90 46,4 s nas 58 (46,8 s nas 57 do devil54: diferença de método, sem efeito) |
| Filtro: US$ 0,00017 por janela | jsonl do filtro (2.964) | US$ 0,000169 |
| Aviso da janela anterior: 98,7% e 98,6% | `prior_after_skip54.txt` | igual |
| Carteiras: vertex 14,67/15,00; aistudio 27,41/28,50; bedrock 2,17/3,50; deepseek 1,54/3,00 | `bench_budget.py` às 02:12 de 22/11 | igual |
| Variáveis do plano (`GATE_PREFILTER_*`, `GATE_BEDROCK_*`, `GEMINI_AGENT1_*`, `GEMINI_GATE_PROMPT_VARIANT`) e padrões (limiar 0,30, só registrando, queda para o Gemini, 15 s por tentativa) | `config.py` da branch do PR #95 | existem, padrões iguais |

## Corrigido

1. **Linha "hoje refeito" com −51% sem explicação** (página e plano). Lida sozinha, parece que o funil de hoje refeito custa metade do de hoje e que o A é pior. Acrescentado: essa linha já tem o filtro na frente dos modelos de hoje (aposentados no Vertex); o A custa mais que ela porque manda mais eventos ao detail (4,85% contra 2,81%) e o detail novo custa cerca do dobro por chamada (US$ 0,0193 no Vertex contra US$ 0,0096 do de hoje em produção).
2. **Critério do passo 2 do plano**: o "28%" era da amostra crua (839 de 2.964, que inclui todos os confirmados e tem mais eventos com detecção que a câmera). Pesado pela mistura da câmera (pesos da seção 0 do devil54), o filtro deixa passar cerca de 20% (18% dos eventos sem disparo). A faixa de 15% a 30% do critério continua certa; a referência passou a ser os 20%.

## Notas sem correção

- No diário 12.13 do arquivo do replay está "o corte de 45 s cortaria cerca de 1 em 10 chamadas"; medido é 8 de 58, cerca de 1 em 7. O plano e a página já usam 8 de 58.
- O `final54__aval.md` fala em "58 eventos S2C em que o gate do A dispara"; o devil54 conta 57 (um dos 58 com resposta do Vertex não conta como disparo do A depois do filtro). Não muda nenhum número.
