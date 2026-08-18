# Campanha 18 - v3 vs esp32 recall baseline (2026-05-26)

> No prompt reached all targets. B2 is the safest sweet spot so far; B3 improves recall but pays in FP.

## Hipotese

O prompt v3 com recall mode para esp32_002 aumenta o recall em TP sem elevar demais FP e disparos em baseline dia/noite.

## Configuracao

| Item | Valor |
|------|-------|
| Gate | `gemini-2.5-flash-lite` |
| Detail | nao executado nesta campanha |
| Thinking budget | 2048 |
| Dataset | `data/datasets/official` |
| Filtro | camera=`cam_mangabeira`, device_id=`esp32_002`, categorias=`tp`,`fp` |
| Baseline | amostra: 10 janelas dia + 10 janelas noite |
| Foco | gate recall tuning para `cam_mangabeira` / `esp32_002` |

## Resultados

<!-- metrics-start -->

| Arm | TP recall | FP catalogado | Baseline | Baseline dia | Baseline noite | Erros | Custo |
|-----|----------:|--------------:|---------:|-------------:|---------------:|------:|------:|
| A_v3 | 2/7 (28,6%) | 16/43 (37,2%) | 2/20 (10,0%) | 1/10 (10,0%) | 1/10 (10,0%) | 6 | $0,0903 |
| B_v3_esp32_recall | 5/7 (71,4%) | 15/43 (34,9%) | 7/20 (35,0%) | 5/10 (50,0%) | 2/10 (20,0%) | 9 | $0,0883 |
| C_v3_esp32_recall_b2 | 5/7 (71,4%) | 14/43 (32,6%) | 0/20 (0,0%) | 0/10 (0,0%) | 0/10 (0,0%) | 0 | $0,1010 |
| D_v3_esp32_recall_b3 | 6/7 (85,7%) | 17/43 (39,5%) | 1/20 (5,0%) | 1/10 (10,0%) | 0/10 (0,0%) | 0 | $0,1016 |
| E_haiku_b2 | 1/7 (14,3%) | 0/43 (0,0%) | 0/20 (0,0%) | 0/10 (0,0%) | 0/10 (0,0%) | 1 | $0,9253 |

### Leitura

- B1 provou que recall pode subir, mas abriu baseline demais.
- B2 corrigiu baseline e schema: `0/20` baseline, `0` erros, melhor FP (`14/43`), mas manteve recall em `5/7`.
- B3 recuperou mais 1 TP (`6/7`) e ficou no limite de baseline (`1/20 = 5%`), mas piorou FP para `17/43`.
- Haiku B2 foi conservador demais para Agent-1: pegou apenas `1/7` TP, zerou FP/baseline, custou cerca de 9,2x mais que Gemini B2 e teve 1 erro de schema por texto longo.
- O TP restante (`d59d5309`, carrinho de mao) nao foi recuperado nem com 42 frames enviados: o modelo classificou como `TRAFFIC/passing_by` e disse nao ver interacao com a pilha.

### Sweet Spot

O melhor candidato operacional agora e **C_v3_esp32_recall_b2**: ele elimina baseline, reduz FP contra A/B1 e nao tem erros de schema. Se a prioridade absoluta for recall, **D_v3_esp32_recall_b3** e o candidato, mas ele aumenta FP e fica exatamente no teto de baseline. **E_haiku_b2 nao serve como Agent-1** nesta camera: recall muito baixo e custo alto.

<!-- metrics-end -->

---

## Decisao

Nao ha prompt que pegue todos os TPs nesta amostra. Para proxima rodada, usar C_v3_esp32_recall_b2 como base e tratar o caso `d59d5309` fora de prompt: melhor selecao temporal de frames, pre-gate com tracking/carrinho, ou revisao do rotulo se a acao nao aparece visualmente.

## Caveats

- Campanha gate-only: Agent-2 nao foi executado.
- Baseline foi amostrado: 10 janelas de dia e 10 janelas de noite.
- Cinco FPs do manifest ficaram fora porque tinham apenas um frame local.
- O resultado de `d59d5309` sugere limite visual/modelo: mesmo com 42 frames, o gate nao reconheceu o carrinho/interacao.
