# Follow-up — Iterações V3 do prompt Gemini (camps 11-14)

**Data:** 2026-05-23
**Autor:** Alexandre Manaca (com auditoria assistida)
**Sessão:** continuação de [docs/prompt_dataset_mismatch_20260522.md](prompt_dataset_mismatch_20260522.md)

## TL;DR

Após o relatório de mismatch (2026-05-22), rodei 4 campanhas iterando o prompt
(V2 com fix carroça → V3 posture-first → V3.1 3-signal gate → V3.2 collection-context).
**Nenhuma versão passou** todos os critérios. O bloqueio é estrutural do modelo
Gemini, não do prompt: ele confabula `posture=depositing_at_pile` em qualquer
cena com pessoa próxima a pilha pré-existente.

**Recomendação:** manter V1 em produção; postergar promoção V2/V3 até termos
sinais comportamentais não-confabuláveis (tracking temporal multi-frame, ou
detecção CV nativa de objetos sendo soltos).

Custo total das 4 campanhas: **$0.94 USD** (gate calls em projeto de teste
`gen-lang-client-0841492152`, nunca produção).

---

## Cronologia das 4 iterações

### Camp 11 — V2 promotion (fix carroça)

- **Hipótese:** V2 com fix carroça (carroça vira sinal neutro) recupera o nível
  de recall do V1 mantendo a redução de FP do V2.
- **Resultado:** ❌ FAIL — V2 melhora FP rate -17pp ✅ mas regrediu recall -10pp.
  Perdeu 2/3 golden cases (`d00a79bd` uniforme, `12506543` pedestre).
- **Achado:** V2 confabula `pile_volume_change=increased` em 13 cenas vazias
  ("person near pile" → "pile grew between frames" — sem evidência visual real).
- **Custo:** $0.22 USD (348 calls × $0.0006).

### Camp 12 — V3 posture-first

- **Hipótese:** postura corporal (`person_position_signature`) como sinal
  primário recupera os 4 TPs que V2 perdeu (descartes pedestres invisíveis na
  resolução CCTV — first/last frame idênticos para o olho humano).
- **Mudanças:** novo campo enum `person_position_signature` (7 valores),
  `apply_v3_gates` com positive override em `posture in {depositing_at_pile,
  leaving_pile_area} + handling=True`, LOCAL_CONTEXT por câmera.
- **Resultado:** ❌ FAIL — V3 ganha recall +15pp (25%→40%, 5 TPs recuperados
  incluindo 2/3 golden) ✅ mas FP rate explode +23pp (16%→40%, 40 FPs novos).
- **Achado crítico:** modelo confabula `posture=depositing_at_pile` em qualquer
  cena com pessoa próxima da pilha. Exemplos:
  - "Apenas um cachorro andando" → modelo INVENTOU pessoa
  - "Pessoa estacionou e desceu com criança" → marcou depositing
  - "Estavam retirando o Lixo" (coleta!) → marcou depositing
  - "Estavam limpando os restos de poda" (poda municipal) → marcou depositing
- **Custo:** $0.25 USD (348 calls).

### Camp 13 — V3.1 stricter 3-signal gate

- **Hipótese:** exigir 3 sinais (`posture + handling + (flow=to_pile OR
  new_ground_material)`) reduz drasticamente as 40 FPs do V3 sem perder
  recall significativo.
- **Mudanças:** prompt detalha 3 sub-condições obrigatórias para
  `depositing_at_pile` (A1 bending visível, A2 carrying object, A3 hands
  empty/different in later frame). Gate exige corroboração adicional.
- **Resultado:** ❌ FAIL — FP rate cai para 12% ✅ MAS recall cai para 20%
  (regressão -20pp).
- **Achado:** modelo seguiu o critério **literalmente demais**: pessoa
  "holding a white bag near the pile" SEM bending claramente visível →
  marcou `standing_near_pile` em vez de `depositing_at_pile`, perdendo TP
  real (`be6b5e67`).
- **7 FPs ainda passaram** (poda/limpeza municipal). Modelo persiste
  marcando `depositing` em cenas de cleaning crew, mesmo com novas
  instruções V3.1.
- **Custo:** $0.13 USD (bench reduzido 164 calls).

### Camp 14 — V3.2 collection-context override (≥2 sinais)

- **Hipótese:** voltar gate a 2 sinais (preserva recall V3) MAS adicionar
  supressão se ≥2 sinais de collection-context aparecem (`scene=COLLECTION_OR_MAINTENANCE`,
  `municipal_equipment_present`, `flow=from_pile`, `pile=decreased`). Isso
  protege contra os 7 FPs de poda/limpeza específicamente, sem regredir o
  golden `d00a79bd` (uniforme) onde modelo às vezes mis-classifica scene
  mas posture é correta.
- **Mudanças:** prompt explica explicitamente que cleaning crews também
  bend down ("if you see brooms/rakes/uniforms AND people bending →
  collection, not dumping"). `apply_v3_gates` conta sinais de collection.
- **Resultado:** ❌ FAIL — **0/3 golden** (pior que V3 original com 2/3).
  TP recall = V2 (31.25% / 31.25%). FP rate sobe +5.7pp (17% → 23%).
- **Achado terminal:** modelo Gemini ignora as instruções de correlação
  rakes/brooms/uniformes → collection. **Confabulação é estrutural**, não
  corrigível só por prompt. A regra de "≥2 sinais de collection" só ajuda
  quando o modelo TAMBÉM emite outros sinais — que ele não emite quando
  full-confabula posture.
- **Custo:** $0.17 USD (284 calls com 110 events para cobrir os 3 goldens).

---

## Por que V3.3 não vale o gasto

Restam ~$0.06 USD do budget aprovado de $1. Para usar bem, precisaria de
uma hipótese que tivesse alta probabilidade de mudar o trade-off
fundamental. As que considerei:

1. **Schema com `posture_confidence` (0-100)** + gate só dispara se >=80.
   Mas o modelo já confabula em alta confiança (conf=90 nos FPs). Schema
   change sem evidência de que isso resolveria.

2. **Hybrid V1+V2+V3 com fallback condicional** (e.g. V3 só quando
   `flow=to_pile`, V2 caso contrário). Complexidade alta, e os campos
   ainda são confabuláveis pelo mesmo modelo. Não há razão para acreditar
   que mudaria o resultado.

3. **Voltar ao V1 com filtros pós-hoc humanos.** Não é prompt, é
   operacional. Fora do escopo desta iteração.

4. **Mudar de modelo (Haiku/GPT/Claude).** Camp 07 já testou Haiku: 23×
   mais caro com Gemini-equivalent ou pior accuracy. Não vale.

5. **Treinar fine-tune ou usar OPENCV/YOLO próprio para detectar
   "objeto sendo solto" frame a frame.** Caminho viável mas é projeto
   separado de semanas, não um bench rápido.

Decidi parar e consolidar achados em vez de queimar o último bench.

---

## Recomendações concretas

### Curto prazo (próximos dias)

1. **Manter V1 em produção.** É o melhor em recall (35% absoluto no dataset
   oficial). Custo de revisão humana de FPs é o preço aceitável.
2. **Não promover V2 sem revisão humana ativa.** V2 reduz FPs mas perde 4
   TPs críticos no dataset oficial (incluindo o caso ⚠️ CRÍTICO `d00a79bd`
   uniforme).
3. **Não promover V3.x** — todos os candidatos falharam, e as variantes
   conservadoras (V3.1, V3.2) sacrificam recall sem ganho líquido em FP.

### Médio prazo (próximas 2-4 semanas)

1. **Investigar tracking multi-frame não-LLM.** O ponto cego que mata o
   V3 é "modelo não consegue ver a transição carrying→empty hands em first
   vs last frame." Um tracker dedicado (e.g. ByteTrack + heurística de
   objeto solto perto da pilha) poderia detectar a transição diretamente
   sem depender de LLM.
2. **Ampliar dataset oficial.** Hoje só 14 TPs. Coletar mais 50-100 TPs
   pedestres com volumetria variada (0.05-1.0 m³) reduziria a variância
   estatística entre runs (vimos V2 dar 25% no full, 40% e 31.25% em
   reduced — variabilidade alta em N pequeno).
3. **Adicionar coluna `gemini_context_notes` na tabela `cameras` (Fase C
   do plano original).** Mesmo que V3 não vá pra prod agora, o campo é
   útil para qualquer iteração futura.
4. **Documentar os FPs típicos por câmera no LOCAL_CONTEXT** em vez de
   tentar resolver tudo no prompt global. Por exemplo: para Mangabeira,
   instrução específica sobre o horário 13h-15h de coleta EMLURB; para
   Imbiribeira, sobre carroceiros em madrugada.

### Longo prazo (próximos meses)

1. **Considerar VLM open-source no-pipeline** (Qwen-VL, MoonDream) com
   fine-tune no dataset oficial. Custo unitário 10-100× menor que Gemini,
   permite eventualmente um pass de classificação MUITO mais barato após
   o gate.
2. **Pesquisa: contexto temporal mais longo** — janelas de 60s+ com 12-24
   frames em vez de 5. Custo dobra/triplica, mas pode reduzir confabulação
   ao dar evidências reais ao modelo.

---

## Lições aprendidas (registrar em lessons.md também)

1. **Sinais que o modelo emite por hábito treinado, ele confabula.**
   `pile_volume_change=increased` e `posture=depositing_at_pile` são
   campos onde o modelo "vê o que espera ver" quando o cenário superficialmente
   se parece com descarte (pessoa + pilha + bending). Adicionar mais
   instruções no prompt não desfaz isso — o modelo escolhe o valor que
   "faz sentido" com sua narrativa, não o que de fato está visível.

2. **Bench reduzido (50-110 events) tem alta variância.** Camp 13 deu V2
   com 40% recall, camp 14 deu V2 com 31% recall — mesmo prompt, mesmos
   eventos, modelo Gemini não é determinístico (mesmo com seed=42). Para
   comparar arms, sempre rodar full bench (174 windows).

3. **Métricas agregadas mascaram trade-offs por evento.** Camp 12 V3
   recuperou 5 TPs reais (achado importante) mas gerou 40 FPs novos. Em
   net o PASS falhou, mas dos 5 TPs ganhos, 3 eram pedestres puros que
   V1/V2 NUNCA pegariam. Existe trade-off real — não é "V3 ruim",
   é "V3 cobre cenários novos com custo de FP".

4. **`apply_v*_gates` lógica determinística pós-modelo é eficaz para
   suprimir, mas NÃO para confirmar.** Quando o modelo está "errado por
   confabulação", lógica determinística não tem como corrigir — só pode
   suprimir, e ao suprimir indiscriminadamente, mata recall também.

---

## Artefatos

- [campaigns/11-prompt-v2-promotion-2026-05-22/report.md](../benchmarks/campaigns/11-prompt-v2-promotion-2026-05-22/report.md)
- [campaigns/12-prompt-v3-posture-2026-05-22/report.md](../benchmarks/campaigns/12-prompt-v3-posture-2026-05-22/report.md)
- [campaigns/13-prompt-v3-1-stricter-2026-05-22/report.md](../benchmarks/campaigns/13-prompt-v3-1-stricter-2026-05-22/report.md)
- [campaigns/14-prompt-v3-2-collection-fix-2026-05-23/report.md](../benchmarks/campaigns/14-prompt-v3-2-collection-fix-2026-05-23/report.md)
- Prompt V3 atual: [services/yolo-worker-vm/src/worker/_prompts_v3.py](../services/yolo-worker-vm/src/worker/_prompts_v3.py) (versão V3.2)
- Tests: [services/yolo-worker-vm/tests/test_v3_gates.py](../services/yolo-worker-vm/tests/test_v3_gates.py) (12 testes, 47/47 verdes incluindo V1/V2/V3)
- Plumb: `GEMINI_PROMPT_VERSION` env var em [config.py](../services/yolo-worker-vm/src/worker/config.py#L108), aceita `current` (default) / `v2` / `v3`. Default produção fica em `current` (V1).
