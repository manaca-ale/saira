# Campanha 45 — Mangabeira pós-mudança: diagnóstico e recuperação de FP

Status: **Fase 0 concluída · Fase 2 em execução**. Atualizado 2026-07-15.

## 1. O problema (medido)

Câmera esp32_002 movida em **09/07** (agora distante do ponto de descarte; descarte a pé).

| Janela | Dias | CONF | REJ | det/dia | Taxa de confirmação |
|---|---|---|---|---|---|
| Antes (25/06–08/07) | 14 | 27 | 69 | 8,1 | **28,1%** |
| Depois (09/07–15/07) | 7 | 12 | 116 | 20,9 | **9,6%** |

Chamadas de gate: ~100/dia → **~400/dia** (custo ~3×).

**Causa imediata**: no dia da mudança o `.env` de prod desligou todos os filtros (`BGSUB_SHADOW_DEVICES=esp32_002` = BGSUB observa mas não bloqueia; `STRUCTURAL_FILTER_MODE/RECOVERY=off`; `GEMINI_DETAIL_PILECROP_ENABLED=false`). Restou como único decisor o cascade Gemini — cujo gate da esp32_002 é **V3 + B3 recall addon hardcoded** (`detector_gemini.py:876`), que escala explicitamente pedestre-com-sacola "even if the bag is small or only visible in one frame" e permite `material_flow_direction="to_pile"` "without full deposit view". Isso colide de frente com a régua do operador, que rejeita com "**Sem flagrante de descarte**".

## 2. Fase 0 — taxonomia dos FPs (classificação cega, 128 detecções)

Classificação visual às cegas (Sonnet, sem acesso ao label) do frame representativo de cada detecção rotulada pós-mudança.

### Rejeitados (n=116) — por tipo × interação com a pilha

| fp_type | none | near | touching | adding | removing | unclear | TOTAL |
|---|---:|---:|---:|---:|---:|---:|---:|
| passerby | 14 | 15 | 0 | 0 | 0 | 0 | **29 (25%)** |
| catador_scavenging | 0 | 7 | 12 | 0 | 1 | 1 | **21 (18%)** |
| unclear | 2 | 12 | 3 | 0 | 0 | 2 | **19 (16%)** |
| pile_only_no_person | 16 | 0 | 0 | 0 | 0 | 1 | **17 (15%)** |
| vehicle_only | 9 | 1 | 0 | 0 | 0 | 0 | **10 (9%)** |
| plausible_real_disposal | 0 | 5 | 2 | 2 | 0 | 1 | **10 (9%)** |
| limpeza_urbana | 1 | 2 | 3 | 1 | 2 | 0 | **9 (8%)** |
| shadow_or_light | 1 | 0 | 0 | 0 | 0 | 0 | 1 (1%) |

### Buckets acionáveis

| Bucket | N | % dos REJ | Alavanca |
|---|---:|---:|---|
| **A. Sem interação alguma com a pilha** | 43 | 37% | **BGSUB** (nada persistente muda na zona) |
| — dos quais sem pessoa nenhuma (alucinação pura) | 16 | 14% | BGSUB |
| **B. `pile_only_no_person`** | 17 | 15% | BGSUB |
| **C. `vehicle_only`** (9/10 sem interação) | 10 | 9% | BGSUB |
| **D. catador + limpeza urbana** | 30 | 26% | ❌ sobrevive a BGSUB **e** structural (persiste E muda a pilha) → só detail HIGHBAR |
| **E. Parecem descarte real** | 10 | 9% | ⚠️ possível divergência de régua do operador (ver §4) |

Distância aparente: `medium` 51 · `far` 45 · `close` 3 — confirma que os sujeitos ficaram pequenos.

### Confirmados (n=12) — o achado metodológico

O classificador cego leu **7 dos 12 confirmados como `catador_scavenging`**. Não é erro dele: **num frame único, "pessoa agachada na pilha depositando" e "catador remexendo" são visualmente idênticos** — a diferença é temporal (material chegou ou saiu). Consequências:

1. Taxonomia de frame único não separa TP de FP nesse ponto — serve para dimensionar buckets, não para decidir.
2. O structural-delta mede **mudança**, não **direção**: catador que remove material também muda tiles. Ele separa "algo mudou" de "nada mudou" (transeunte) — **não** separa depósito de remoção. Isso limita o bucket D por construção.

## 3. Geometria — o polígono e o threshold

`cameras.pile_zone_polygon` (cam 11) = `[[496,322],[554,357],[660,328],[610,298]]`, `updated_at = 2026-05-27` (**anterior à mudança**). Ele **acerta o núcleo da pilha** na vista nova (o usuário estava certo), mas:

- **Área = 5.006 px²**. O BGSUB de prod suprime quando `persistence_px < 1000` — ou seja, exige que **20% da zona inteira** esteja persistentemente alterada. Uma sacola a essa distância tem poucas centenas de pixels ⇒ com o threshold atual, BGSUB em enforce **suprimiria descartes reais**. O threshold é a variável crítica, não só o polígono. (Por isso o sweep varre thr de 100 a 5000.)
- **Perde depósitos reais na borda**: carroça de 11/07 (x≈640-700) e sacola de 10/07 (x≈660-720, y≈345-370) caem fora/na borda.
- Os `waste_bbox` do Gemini nas confirmadas (união x 384-768, y 324-540) estão sistematicamente deslocados para o asfalto — apoio, não fonte (lição camp 44). A geometria foi lida das imagens confirmadas (`viz/polygon_current_vs_proposed.png`).

Candidatos em `polygons.json`: `proposed` (15.328 px², 3,1×, cobre os 6 depósitos inspecionados, para em x=740 antes da faixa de carros estacionados em x≥755) e `proposed_tight` (controle conservador). **O sweep decide** — nenhuma zona é adotada sem passar no critério duro.

## 4. Ponto para o cliente/operador (bucket E)

10 rejeitados (9%) mostram pessoa **carregando objeto no ponto de descarte** — ex.: `5bf5030e` (pessoa carrega objeto volumoso na cabeça em direção à pilha), `8305da52` (pessoa em pé no ponto com sacola rosa, ao lado de um saco branco já no chão). Os comentários do operador são "Sem flagrante de descarte": a régua é **ver o ato**, não a intenção. Isso é exatamente o que o B3 addon manda escalar. Decisão de produto: ou o pipeline sobe a régua para flagrante (HIGHBAR), ou parte desses 9% continuará virando rejeição.

## 5. Fase 2 — backtest (em execução)

Corpus: **114.872 frames** (7,54 GB), dias 09–15/07 contínuos a 5s, 0 buracos relevantes (só uma interrupção real de 13,5 min em 09/07 09:17). Manifest: **2.498 janelas** reconstruídas do audit, 0 incompletas (14 registros CONF / 139 REJ — janelas coalescidas compartilham `detection_id`).

### 5.1 Structural-delta — ❌ REPROVADO para enforce (o receio do usuário se confirma)

153 janelas rotuladas, 1º-vs-último frame, census+Hamming prod-exato (`worker.detector_structural.score_window` importado direto).

| Zona | Tile | AUC (keep CONF) | CI95 | Veto @100% CONF | REJ mortos |
|---|---|---|---|---|---|
| current | 32 | 0,555 | [0,426–0,681] | thr=0 | **0/139** |
| current | 16 | 0,588 | [0,439–0,725] | thr=0 | **0/139** |
| proposed | 32 | **0,460** | [0,330–0,590] | thr=0 | **0/139** |
| proposed | 16 | 0,563 | [0,447–0,678] | thr=2 | 33/139 (24%) |

**Todos os CI incluem 0,5** — nenhuma separação estatisticamente estabelecida. Comparar com a camp 41 na cena antiga: **AUC 0,827**. A alavanca de visão que sobrevivia a holdout temporal **colapsou com a distância**: as CONF produzem mediana de **1 tile mudado** em t32 (o depósito não muda 50% de um tile de 32px), e o `STRUCTURAL_NTILES_THR=2` de prod rejeitaria a maioria dos descartes reais. O único ponto operável (proposed/t16, thr=2 → 33 REJ mortos, 14/14 CONF) tem margem de navalha: o mínimo das CONF é exatamente 2. **Veredicto: não enforçar; no máximo shadow.**

### 5.2 O polígono — evidência quantitativa independente

`n_tiles` mudados (t16) nas 14 janelas confirmadas:

| Zona | CONF com ZERO mudança | mediana CONF |
|---|---|---|
| **current** | **2/14** (`1e0b1bb5` 08:19, `fec7d216` 00:25) | 6 |
| **proposed** | **0/14** | 8 |

Duas janelas confirmadas **não registram nenhuma mudança dentro do polígono atual** — prova direta de que o depósito ocorreu fora dele. O polígono proposto captura todos os 14 e amplifica o sinal onde importa (carroça `ef69c6e4`: 8 → **31** tiles; `e27740cb` 2ª janela: 1 → 13). Isso vale para BGSUB e pilecrops também, que derivam a geometria do mesmo polígono.

### 5.3 BGSUB — cross-check com o ledger de PRODUÇÃO (polígono atual) 🚨

O worker grava toda avaliação do BGSUB no ledger mesmo em shadow. Cruzando `gate_request_id` → audit → `detection_id` → operador (`scripts/ledger_crosscheck.py`): **2.715 decisões reais** pós-mudança, 178 com detecção associada.

| Grupo | n | min | p10 | p50 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|
| CONFIRMADO | 14 | **0** | 0 | 1.391 | 6.700 | 10.784 |
| REJEITADO | 139 | 0 | 0 | 260 | 6.263 | 28.055 |
| NEG (sem trigger) | 2.348 | 0 | 0 | 50 | 3.813 | 53.513 |

Há sinal na mediana (CONF 1.391 vs REJ 260 = 5×), **mas o piso das CONF é 0**: qualquer threshold ≥ 1 mata descartes reais.

| thr | CONF mortos | REJ mortos | NEG suprimidos |
|---:|---|---|---|
| 50 | **5/14** | 53/139 (38%) | 1.174/2.348 (50%) |
| 300 | **5/14** | 70/139 (50%) | 1.401/2.348 (60%) |
| **1000** (valor de prod) | **6/14** | 95/139 (68%) | 1.731/2.348 (74%) |
| 3000 | **11/14** | 119/139 (86%) | 2.064/2.348 (88%) |

**Conclusão crítica: religar `BGSUB_SHADOW_DEVICES=` (enforce) hoje, com o polígono atual e thr=1000, mataria 5 de 12 detecções confirmadas (~40% do recall).** Restaurar a receita pré-mudança "como estava" seria um desastre. Não existe threshold seguro com a geometria atual.

#### As duas causas de falha (por janela confirmada, dados de prod)

| det | janela | persist | frames_ok | BGSUB |
|---|---|---:|---:|---|
| ff82fb9c | 12/07 06:08 | 10.784 | 48/48 | passa |
| e27740cb | 09/07 15:59 | 6.700 | 47/47 | passa |
| ef69c6e4 | 11/07 12:03 | 2.403 | 44/44 | passa |
| 1e0b1bb5 | 10/07 08:19 | 1.414 | 42/48 | passa |
| **305e0ed3** | 12/07 09:37 | **344** | 29/40 | ❌ filtra |
| **fec7d216** | 11/07 00:25 | **9** | 20/40 | ❌ filtra |
| **06ebe145** | 09/07 23:56 | **0** | 18/43 | ❌ filtra |
| **090dbbcc** | 11/07 11:23 | **0** | 16/45 | ❌ filtra |
| **356f26ed** | 15/07 12:04 | **0** | **2/43** | ❌ filtra |

1. **Depósito fora do polígono** (`356f26ed`: só 2 de 43 frames têm qualquer foreground na zona) → corrigido pelo polígono `proposed`.
2. **Depósito tardio na janela** (`06ebe145`, `090dbbcc`: foreground em 16-18 de ~44 frames, mas persistence 0) → com `BGSUB_MIN_PERSISTENCE_FRAMES=0,4` numa janela de 240 s, o objeto precisa estar presente em **40% dos frames**; quem descarta nos últimos 60 s nunca atinge isso. **`mf=0,4` é parâmetro errado para esta cena**.
3. **Gate de ruído por frame alto demais** — `BGSUB_MIN_PX_ACTIVE=800`: um frame com menos de 800 px de foreground na zona contribui **zero votos** (`bgsub_filter.py:512`). Uma sacola a essa distância tem poucas centenas de px ⇒ depois que a pessoa sai de quadro, os frames que contêm **só o material depositado** são descartados. É a explicação de `frames_ok=2/43`.

**Os três parâmetros são as três variáveis do BGSUB — e nenhum deles foi recalibrado após a mudança de posição.** Todos são ajustáveis **por câmera** via colunas do banco (`bgsub_persistence_threshold`, `bgsub_min_persistence_frames`, `bgsub_min_px_active`, `camera.py:33-41`, lidas por `_resolved_config`), ou seja, o ajuste **não afeta esp32_001/005**.

### 5.3.1 Resultado do sweep BGSUB (462 janelas × 4 eixos) 🧭

Critério: **0 de 12 detecções confirmadas perdidas** (agregado por detecção; em prod a detecção nasce na 1ª janela que escapa do filtro). Melhor operating point por zona:

| Zona (npz prod) | min_px | mf | thr | CONF perdidas | REJ mortas | NEG suprimidas (custo) |
|---|---|---|---|---|---|---|
| **current** | 800 | 0,30 | 50 | **0/12** | **36/116 (31%)** | 33/120 (28%) |
| proposed_tight | 100 | 0,20 | 1500 | 0/12 | 20/116 (17%) | 3/120 (2%) |
| proposed | 100 | 0,20 | 1500 | 0/12 | 7/116 (6%) | 0/120 (0%) |

**Três descobertas:**

1. **O BGSUB ficou fraco nesta cena.** O teto preservando 100% dos TPs é **~31% das rejeitadas** e **~28% das vazias** — longe dos 72% de supressão que tinha antes da mudança. Descarte distante = pouco sinal ⇒ threshold baixo ⇒ filtro permissivo. O BGSUB deixa de ser alavanca de FP e vira, no máximo, redutor parcial de custo.
2. **`mf=0,4` (prod) era o erro central.** Baixando para `mf=0,30`, as persistences das confirmadas saltam (as 5 que davam 0-344 no ledger real passam a 983-2918) porque o objeto depositado não precisa mais estar em 40% dos 44 frames. Delay: só `1e0b1bb5` nasce 1 janela depois (~4 min); as outras 11 passam na 1ª.
3. **Contraintuitivo — a zona `current` (menor) suprime MELHOR que a `proposed`.** A zona ampla inclui a calçada/meio-fio onde pedestres transitam → mais foreground persistente de rua → o filtro deixa passar mais (proposed mata só 6% das REJ). Para o **BGSUB**, zona estreita é melhor.

**Tensão de geometria a resolver:** BGSUB quer zona estreita (`current`); os **pilecrops do detail** usam o *bounding box* do polígono (`_pile_bbox`, `main.py:1188`) e querem zona ampla (`proposed`) para o crop de alta-res cobrir onde os depósitos caem (a carroça de 11/07 está fora do bbox de `current`). Como as duas alavancas leem a **mesma** coluna `pile_zone_polygon`, o A/B do detail (§5.5) é o árbitro: se o HIGHBAR sozinho resolve o FP, a escolha do polígono é ditada pelos pilecrops (proposed) e o BGSUB fica secundário; caso contrário, pesa o trade-off.

### 5.5 A/B offline do detail (pilecrops + HIGHBAR) — em execução

4 braços sobre as 153 janelas rotuladas, input replicado 1:1 de prod (`scripts/detail_ab.py`, chamada real `analyze_with_gemini`, Vertex projeto de testes): **A** = prod hoje (V3 sem crops); **B** = pilecrops `proposed` + HIGHBAR; **C** = pilecrops `proposed` + prompt E (isola crops de HIGHBAR); **D** = pilecrops `current` + HIGHBAR (isola o polígono). Critério duro 12/12 CONF. Resultados: pendente.

### 5.4 Decomposição da explosão de FP (audit pré vs pós-mudança) 🎯

Comparação direta dos registros de auditoria do cascade, 8 dias antes (01–08/07, **pilecrops+HIGHBAR ligados, BGSUB enforce, structural recovery enforce**) vs 7 dias depois (09–15/07, tudo desligado):

| Métrica | Antes (01–08/07) | Depois (09–15/07) | Δ |
|---|---:|---:|---|
| Janelas avaliadas/dia | 111 | **357** | **3,2×** |
| Gate triggers/dia | 37 | 52 | 1,4× |
| Taxa de trigger do gate | 33,1% | 14,7% | — |
| Agent-2 rodou (total) | 353 | 377 | **1,07×** |
| **Taxa de rejeição do Agent-2** | **73,9%** | **52,8%** | **−21 pp** |
| Detecções/dia | 11,5 | 25,4 | 2,2× |

Duas causas independentes, e a atribuição é limpa:

1. **BGSUB enforce → shadow = driver de CUSTO.** As janelas que chegam ao gate triplicaram (111 → 357/dia): o BGSUB suprimia ~69% delas antes do gate. É isso que produz as ~400 chamadas de gate/dia.
2. **pilecrops+HIGHBAR → V3 genérico = driver de FP.** O Agent-2 rodou praticamente o **mesmo volume** (353 → 377), mas passou a confirmar **o dobro**: a rejeição caiu de 73,9% para 52,8%. Com o mesmo volume e a rejeição antiga, seriam ~98 detecções em vez de 178 — **~45% menos**.

**Conclusão que inverte a prioridade: o maior gerador de FP não é a geometria, é o prompt do detail.** O `DETAIL_PROMPT_MANGABEIRA_HIGHBAR` sobe a régua para *flagrante* — exatamente a régua do operador ("Sem flagrante de descarte") — e está inerte desde 09/07 porque só ativa com `GEMINI_DETAIL_PILECROP_ENABLED=true` (`_prompts_v3.py:752-767`). Reativá-lo é **uma linha de env**, e é a única alavanca do bucket D (catador/limpeza, 26%).

Observação: `agent2_ran` (353) > gate triggers (295) antes da mudança = a **structural recovery** em enforce escalava ~58 janelas gate-rejeitadas para o Agent-2 (16% das chamadas). Esse caminho morreu com o structural (§5.1) — e deve continuar off.

⚠️ Pré-condição: o bbox dos pilecrops **deriva do polígono** (`_pile_bbox`, `main.py:1188-1198`). Religar pilecrops com o polígono stale recortaria a região errada (a que perde 2/14 confirmados). **Polígono primeiro.**

## 6. Decisão

Parcial:
- ❌ **Structural-delta**: não enforçar (AUC colapsou 0,827 → 0,46-0,59 com a distância). Reavaliar só se a câmera reaproximar.
- ✅ **Polígono**: trocar pelo `proposed` — 2/14 confirmados ficavam fora do atual.
- ⏳ **BGSUB**: aguardando sweep (é agora a alavanca principal — buckets A+B+C = 52% dos rejeitados).
- ⏳ **Detail pilecrops+HIGHBAR**: reativar (era parte da receita que dava 28%; `DETAIL_HIGHBAR_DEVICES=esp32_002` já está setado e inerte). Única alavanca do bucket D (26%).

## Caveats

- Taxonomia de frame único não distingue depósito de remoção (§2). Buckets são estimativas de tamanho, não ground truth.
- 12 CONF é amostra fina para um critério de 0/12 — guarda TRIG (189 janelas gate-positivas) usada como proxy de recall.
- Nomes de frame estão em **BRT** (não UTC); prefixo S3 é data de movimentação, não de captura (38 frames capturados em 09/07 vivem em `day10/`).
