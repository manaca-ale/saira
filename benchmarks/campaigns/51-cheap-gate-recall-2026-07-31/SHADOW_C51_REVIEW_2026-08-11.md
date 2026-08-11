# Shadow C51 — Revisão de 2026-08-11 (7 dias completos, 04–11/08)

Shadow ativo na `pi-cam-001` desde 04/08 (PR #80): gate **A** = `gemini-3.1-flash-lite` e gate **B** = `magistral-small` (prompt `g3`, 5 frames) rodando em paralelo ao gate de prod; detail **kimi-k2.5** (15 frames) quando A ou B dispara. Ledger: `STATE_DIR/shadow_c51_audit/{date}/pi-cam-001.jsonl` no worker de prod.

## Números do período (4.401 janelas, 8 dias parciais)

| Métrica | Gate A (3.1-flash-lite) | Gate B (magistral) |
|---|---|---|
| Fire rate (janelas) | **7,7%** (337) | 26,2% (1.152) |
| Erros / JSON inválido | 5 | 7 |
| Custo do gate (período) | $4,96 | $7,98 |
| Runs do detail induzidos | 337 (só-A 149 + ambos 188) | 1.152 (só-B 964 + ambos 188) |

- Detail kimi: 1.301 runs (29,6% das janelas), $8,63; `would_confirm` em 210 janelas.
- **Custo total: $21,57** → **$0,0049/janela** (~$3,00/dia) — **75% acima da estimativa de $0,0028/janela** do deploy; o orçamento diário de $3,50 quase estourou em 07/08 ($3,35). O motor do custo é o B: gera 74% dos runs do detail.
- Cobertura: 27/27 eventos do DB têm janela no ledger; zero buracos.

## Recall (proxy = operador)

Dos **3 eventos CONFIRMADO** pelo operador no período: **A disparou em 3/3, B em 3/3, kimi confirmaria 3/3**. Nenhum braço perdeu evento confirmado. (n pequeno — 3 eventos.)

## Carga de FP (vs operador)

Dos **22 REJEITADO**: A disparou em 11 (50%), B em 17 (77%) — mas o pipeline shadow completo (gate→kimi) **confirmaria só 6 dos 22 (27%)**. Ou seja: o encadeamento com kimi teria mandado ao operador ~4× menos FP do que o pipeline atual mandou. Os 2 INDETERMINADO: kimi confirmaria ambos.

## Candidatos a FN de prod — precisa arbitragem

**197 eventos** em que o kimi confirmaria e prod **não criou detecção** (A alcança 95; **102 só via B**). Heurística por texto de evidência: ~121 "flagrante-like", ~46 coleta/limpeza (FP clássico), ~30 outros.

⚠️ **Não tratar como 197 FNs reais**: ~25 candidatos/dia é implausível (prod cria ~3-4 detecções/dia e o recall de bench do pipeline é 80-87%); contra os rótulos conhecidos o kimi passa 27% dos REJEITADO. A maioria provável é FP do kimi (revira/coleta) — mas o padrão dos FNs conhecidos de 01/08 (13:03 e 21:09) diz que existem FNs reais no meio. **Próximo passo obrigatório: rotular uma amostra (~20) com os frames** antes de citar qualquer número de FN.

## Recomendação

1. **Gate A (`gemini-3.1-flash-lite`) segue como candidato a gate da migração** — confirma o achado da Fase A da camp 51 (recupera os TPs que o gate de prod perde) agora com 7 dias de prod: recall 3/3 nos confirmados, fire rate 7,7%, 5 erros em 4.401 janelas.
2. **Desligar o gate B (magistral)** ou reduzi-lo a amostragem: dispara 3,4× mais que A, causa 74% do custo do detail (~$1,60/dia dos ~$3,00) e seu único ganho exclusivo (102 candidatos só-via-B) está não-arbitrado. Se quisermos esse sinal, rotular a amostra ANTES de pagar mais uma semana.
3. Kimi como detail continua promissor (corta 73% dos FP que o operador rejeitaria), consistente com camps 48/49.

## Reproduzir esta análise

```bash
ssh saira-prod "docker exec saira-yolo-worker-prod sh -c 'cat /app/state/shadow_c51_audit/*/pi-cam-001.jsonl'" > ledger.jsonl
# detecções: SELECT id,event_ref,timestamp,status FROM detections WHERE camera_id=15 AND created_at>='2026-08-04 13:00'
# cruzar por event_ref; recall = eventos CONFIRMADO com fire_v1 em >=1 janela; FP = idem nos REJEITADO
```
