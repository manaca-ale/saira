# Campanha 11 — Promoção do prompt V2 (com fix carroça) — 2026-05-22

> ❌ **FAIL** — V2 não atingiu os critérios: Δ recall -10.0pp < 10pp, golden cases 1/3. Não promover sem investigação. Escrever follow-up doc com hipóteses de fix.

**Hipótese:** V2 (com fix carroça) atinge TP recall ≥ 25% e FP rate ≤ 43.8% no dataset
oficial v1 com 5 frames/janela. Adicionalmente deve acertar 3 casos golden:
`d00a79bd` (uniforme), `12506543` (pedestre), `fb4a2c50` (FP coleta rejeitada).

**Modelos:**

- Gate: `gemini-2.5-flash-lite`
- Detail: `gemini-2.5-flash`
- Thinking budget: `1024` (fixo nos 2 arms — sweet spot validado em [project_thinking_budget_validated](../../../C:/Users/aleco/.claude/projects/c--saira/memory/project_thinking_budget_validated.md))

**Arms:**

- A_current: `prompt_version="current"` (V1 atual em produção)
- B_v2_patched: `prompt_version="v2"` (V2 com fix carroça aplicado em 2026-05-22)

**Dataset:** [data/datasets/official/](../../../data/datasets/official/) com
filtros: câmeras=[mangabeira, imbiribeira], categorias=[tp, fp, indefinido, missed, baseline].

**Foco:** TP recall em descartes pedestres (12 de 14 TPs) e uniformizados, sem regressão
significativa em FPs de coleta municipal.

---

## Resultados

<!-- metrics-start -->

### Comparação A_current (V1) vs B_v2_patched (V2 com fix carroça)

| Métrica | A_current (V1) | B_v2_patched | Δ (B-A) | Regra | Veredito |
|---------|-----------------|---------------|----------|-------|----------|
| Frames/janela (avg) | 4.98 | 4.98 | — | — | — |
| **TP recall total (%) [n=positivos]** | 35.00 | 25.00 | -10.0pp | B >= 25.0% | ✅ |
|   delta vs A | — | -10.0pp | — | B-A >= 10pp | ❌ |
|   TP recall só TP catalogados (%) | 50.00 | 35.71 | — | (informativo) | — |
|   Missed recall (%) | 0.00 | 0.00 | — | — | — |
| **FP rate total (%) [FP+baseline]** | 33.58 | 16.42 | -17.2pp | B <= 43.8% | ✅ |
|   FP rate só FP catalogados (%) | 58.11 | 22.97 | — | — | — |
|   FP rate só baseline (%) | 3.33 | 8.33 | — | — | — |
| Indef trigger rate (%) | 70.00 | 30.00 | — | informativo (V2 ≠ suprimir todos) | — |
| Cost/call (USD) | 0.00 | 0.00 | — | (informativo) | — |
| Gate cost total (USD) | 0.10 | 0.12 | — | — | — |
| Detail spillover (USD) | 0.33 | 0.17 | — | — | — |
| **Blended cost (USD)** | 0.43 | 0.28 | — | (informativo) | — |
| Latency p50 (ms) | 4981 | 4897 | — | — | — |
| Latency p95 (ms) | 6718 | 5953 | — | — | — |

### Golden cases (PASS criterion)

| Golden case | Esperado | B_v2 retornou | Veredito | Razão |
|-------------|----------|----------------|----------|-------|
| d00a79bd | ✅ detected | ❌ rejected (conf=0) | ❌ | TP uniforme — V2 deve detectar |
| 12506543 | ✅ detected | ❌ rejected (conf=0) | ❌ | TP pedestre puro — V2 deve detectar |
| fb4a2c50 | ❌ rejected | ❌ rejected (conf=0) | ✅ | FP coleta caminhão — V2 deve rejeitar |

### Por câmera (detectar regressão por geometria)

| Câmera | A TP recall | B TP recall | Δ | A FP rate | B FP rate | Δ |
|--------|--------------|--------------|----|------------|------------|----|
| cam_mangabeira | 30.8% (4/13) | 15.4% (2/13) | -15.4pp | 65.1% (28/43) | 18.6% (8/43) | -46.5pp |
| cam_imbiribeira | 42.9% (3/7) | 42.9% (3/7) | +0.0pp | 48.4% (15/31) | 29.0% (9/31) | -19.4pp |

### Categorias do dataset

| Categoria | N |
|-----------|---|
| TP catalogados | 14 |
| Missed (sistema não capturou em prod) | 6 |
| FP catalogados | 74 |
| Baseline | 60 |
| Indefinido | 20 |

### Diffs por evento (A → B)

#### ✅ TPs/Missed que B ganhou (V1 perdeu, V2 pegou) — ESPERADO (2 eventos)

| event_id | câmera | categoria | justificativa | B evidence |
|----------|---------|-----------|---------------|------------|
| 454c8308 | cam_imbiribeira | tp | Um homem realizando o descarte de lixo com um carrinho de mão | Two individuals in red/orange are observed near a growing pile of debris on the right side of the road. The pile visibly increases in volume |
| cb49921a | cam_imbiribeira | tp | Pessoas realizando o descarte do conteúdo de um saco marom aparentemente | A white truck is parked near a large pile of waste. Multiple individuals are present and appear to be actively depositing material onto the  |

#### 🔴 TPs/Missed que B perdeu (V1 pegou, V2 não) — REGRESSÃO (4 eventos)

| event_id | câmera | categoria | justificativa | B evidence |
|----------|---------|-----------|---------------|------------|
| 2bb892bc | cam_mangabeira | tp | Pessoas descartando restos de poda | People are observed interacting with a waste pile. In the first frame, a person is near the pile. In subsequent frames, individuals appear t |
| 48350bb4 | cam_imbiribeira | tp | Dois homens descartando o conteúdo dentro de um grande saco/pano branco | A white truck is parked in the scene. Two individuals are walking in the vicinity. A white sheet is present on the ground but no active mate |
| a73a3f44 | cam_imbiribeira | tp | Caminhonete azul escura realiza o descarte de um grande volume de lixo | A person is visible in the scene, and vehicles are parked. No clear evidence of material being dumped or collected. The ground material appe |
| d00a79bd | cam_mangabeira | tp | Grande quantidade de lixo descartada por um homem utilizando uniforme laranja | A person in an orange vest is seen pushing a cart towards a pile of waste. The pile of waste appears to decrease in volume from the first to |

#### 🟡 FPs/baseline que B passou a confirmar (V1 rejeitava, V2 confirma) — REGRESSÃO (13 eventos)

| event_id | câmera | categoria | justificativa | B evidence |
|----------|---------|-----------|---------------|------------|
| 07925285 | cam_imbiribeira | fp | Pessoa passando com um carrinho | A person is actively handling material on the ground next to a growing waste pile. A vehicle is stopped nearby. The material flow is towards |
| 1c823d95 | cam_mangabeira | fp | Pessoa apenas estacionou e desceu com uma criança | A person is seen interacting with an open car door near a pile of debris. The pile appears to grow between the first and last frame, and the |
| 38982b91 | cam_mangabeira | fp | Pessoas passando e pombos andando sobre o lixo | A person in an orange vest is observed near a pile of debris. The debris pile appears to have increased in volume between the first and last |
| 50e938ae | cam_imbiribeira | fp | Pessoas passando | A white car is parked near a pile of waste. Two individuals are present and appear to be handling material. The waste pile on the right side |
| 6090fa86 | cam_mangabeira | fp | Pessoas passando | A person is present near a parked car and a pile of debris on the ground. The pile appears to have grown between the first and last frames,  |
| 767e7d17 | cam_imbiribeira | fp | Nada ocorrendo | A person is present near a growing pile of waste on the ground. The pile volume increased from the first to the last frame, indicating mater |
| baseline | cam_imbiribeira | baseline |  | A wooden cart is present near a growing pile of waste on the ground. The pile appears to increase in volume between the first and last frame |
| baseline | cam_imbiribeira | baseline |  | The scene shows an orange cart (carroça) filled with waste, and people are present near it. The pile of waste on the ground to the left of t |
| baseline | cam_imbiribeira | baseline |  | The amount of loose debris on the ground appears to have increased between the first and last frames. An orange cart is present, but no pers |
| baseline | cam_mangabeira | baseline |  | The waste pile on the ground appears to have increased in volume between the first and last frames. A vehicle is present and stopped in the  |
| baseline | cam_mangabeira | baseline |  | A person is observed near a waste pile, and the waste pile appears to have increased in volume between the first and last frames, indicating |
| e014c555 | cam_mangabeira | fp | Pessoas passando | Two individuals are present near a growing pile of waste. The pile appears to have increased in volume between the first and last frames, su |
| fc335631 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | A dark SUV is parked near a waste pile. Multiple individuals are gathered around the pile, actively handling material. The waste pile appear |

#### ✅ FPs/baseline que B rejeitou (V1 confirmava, V2 rejeita) — ESPERADO (36 eventos)

| event_id | câmera | categoria | justificativa | B evidence |
|----------|---------|-----------|---------------|------------|
| 10bfef31 | cam_mangabeira | fp | Estavam limpando os restos de poda | People in green uniforms are actively working around a pile of debris and vegetation. A truck with an open, tilted bed is present. The mater |
| 14698616 | cam_mangabeira | fp | Pessoas passando | A vehicle is moving through the scene, and people are visible walking. No material is being actively dumped or collected, and no specific mu |
| 17ff7912 | cam_mangabeira | fp | Estavam realizando a poda | A small truck is parked. Multiple individuals are observed interacting with a debris pile on the ground, picking up material and placing it  |
| 1a2c6dc6 | cam_imbiribeira | fp | Pessoas passando | Vehicles are observed moving through the scene in multiple frames. No clear evidence of material dumping or collection is present. The groun |
| 1cc35595 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | The scene shows parked vehicles and people present, but no active material dumping or collection is observed. The waste pile on the ground a |
| 3f5e4001 | cam_imbiribeira | fp | Apenas está chovendo | A person in an orange vest is operating a small loader/cart near a pile of material. The pile appears to be decreasing in volume, and the pe |
| 3fb685f6 | cam_mangabeira | fp | Pessoas passando | A person is seen collecting material from the ground and moving it towards a vehicle. The pile of waste on the ground appears to be decreasi |
| 4b6e9df1 | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | The scene shows a truck and two individuals wearing orange vests. The individuals appear to be actively moving material from the ground towa |
| 4c5262d9 | cam_mangabeira | fp | Estavam limpando os restos de poda | A truck is parked and two individuals are actively loading green vegetal material (branches, leaves) from the ground into the truck bed. The |
| 4cca7f5d | cam_mangabeira | fp | Estavam retirando o Lixo | Two individuals in green uniforms are observed interacting with a flatbed truck and debris on the ground. The material on the ground appears |
| 4ed80e61 | cam_mangabeira | fp | Pessoas passando | A truck is parked on the side of the road. A person is visible near the truck, holding an object, but their action (dumping or collecting) i |
| 4f356133 | cam_mangabeira | fp | Estavam limpando os restos de poda | A person in green is actively gathering material from the ground and placing it into a truck loaded with green waste. The truck is stationar |
| 51a9ff0e | cam_mangabeira | fp | Estavam retirando o Lixo | A truck is stopped, and a person is actively handling material near the truck. The pile of waste on the ground appears to be decreasing in v |
| 5b109f46 | cam_mangabeira | fp | Estavam limpando os restos de poda | A truck is parked, and individuals are actively gathering debris and vegetation from the ground and loading it into the truck. The pile on t |
| 5e3e79cd | cam_mangabeira | fp | Estavam retirando o Lixo | A large truck is stationary, and several individuals in blue uniforms are actively moving material from a pile on the ground into the truck' |
| 61c6be4e | cam_mangabeira | fp | Estavam limpando os restos de poda | A flatbed truck is parked. A person is present and interacts with the ground near a pile of debris and a bicycle. The pile of debris appears |
| 655ea4ae | cam_imbiribeira | fp | Apenas está chovendo | A vehicle and a person are present and stationary in the scene. No active material dumping or collection is observed. The scene does not sho |
| 765854fa | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | A caminhão compactador (garbage truck) is present and stationary. People are observed near the truck and interacting with the material on th |
| 7bf988b9 | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | A large municipal garbage truck (caminhão compactador) is present and stationary. People are observed near the truck, and the visible waste  |
| 7c0cdfaa | cam_mangabeira | fp | Dois homens trocando objetos, parece um descarte mas eles apenas usam o local pa | Two individuals are observed interacting with a pre-existing waste pile. Across the frames, they appear to be sorting or collecting material |
| 7f2c82ab | cam_imbiribeira | fp | Coleta do lixo sendo realizada | A large green municipal garbage truck (caminhão compactador) is stationary. A person in an orange vest is near the truck's rear hopper, appe |
| 8e92e6c3 | cam_mangabeira | fp | Estavam limpando os restos de poda | A person in a green uniform is seen interacting with a debris pile next to a truck. The pile appears to decrease in volume between the first |
| 983dc78f | cam_mangabeira | fp | Pessoas passando | The scene shows a pile of trash on the ground. A person is present near the trash and a large dark object, but their activity is not clearly |
| 9c631112 | cam_mangabeira | fp | Estavam retirando o Lixo | A truck is stopped, and several individuals in blue uniforms are actively collecting debris from the ground and loading it into the truck. T |
| a3dea6cb | cam_mangabeira | fp | Estavam retirando o Lixo | A truck is stopped with two individuals. One individual is inside the truck bed, actively moving debris. Another individual is standing on t |
| a5db27cc | cam_mangabeira | fp | Estavam limpando os restos de poda | A person in a green uniform is actively collecting vegetation from a pile on the ground and loading it into the bed of a stationary truck. T |
| b014d1e6 | cam_mangabeira | fp | Pessoas passando | A large municipal garbage truck (caminhão compactador) is stopped. A person is seen handling material on the ground near the pile. The pile  |
| b131bc54 | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | A white truck is parked in the scene. Two individuals are present near the truck, but they are not actively handling or depositing material. |
| b489a0a9 | cam_mangabeira | fp | Estavam limpando os restos de poda | The scene shows a truck with a tilted bed and workers in green uniforms. The primary activity observed is the removal of green waste and deb |
| b58f9b56 | cam_mangabeira | fp | Apenas um homem passando de bicicleta | A person on a wooden cart (carroça) is observed near a pile of waste. The person appears to be handling material, and the overall volume of  |
| baseline | cam_imbiribeira | baseline |  | A wooden cart is present, and a person walks through the scene. No active dumping or collection is observed. Vehicles in the background are  |
| baseline | cam_imbiribeira | baseline |  | Multiple vehicles are parked in the scene. A person is visible walking but not actively handling material. The orange bin is present but no  |
| d588e2b2 | cam_mangabeira | fp | Estavam realizando a poda | A person is seen actively handling material on the ground near a pile of debris. The pile appears to have decreased in volume between the fi |
| e811d8bc | cam_mangabeira | fp | Estavam limpando os restos de poda | A person in green is observed collecting debris from the ground and loading it into the trailer of a parked truck. The pile of debris on the |
| f58d2688 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | The scene shows vehicles parked on the street and a person walking. There is no clear indication of material being dumped or collected. The  |
| fb4a2c50 | cam_mangabeira | fp | Estavam retirando o Lixo | A large green municipal garbage truck (caminhão compactador) is stationary. Multiple individuals in blue uniforms are observed working aroun |

#### 🟡 Indef que B passou a marcar detected (V1 não marcava) (1 eventos)

| event_id | câmera | categoria | justificativa | B evidence |
|----------|---------|-----------|---------------|------------|
| 3c60eccd | cam_imbiribeira | indefinido | Três homens mexendo em uma carroça, no lixo e queimando com fogo um objeto | A yellow loader vehicle is present with multiple people around it. The loader appears to be depositing material onto the ground, and the pil |

#### ✅ Indef que B parou de marcar detected (V1 marcava) (9 eventos)

| event_id | câmera | categoria | justificativa | B evidence |
|----------|---------|-----------|---------------|------------|
| 3497125c | cam_imbiribeira | indefinido | Dois homens com uma carroça estão mexendo no lixo | The scene shows a street at night with a blue car visible in the distance in multiple frames. In the later frames, another vehicle and two i |
| 3f115960 | cam_imbiribeira | indefinido | Pessoas perto da carroça | A person is actively handling material near a wooden cart. The pile of waste on the ground appears to be decreasing in volume, and the perso |
| 62894ccc | cam_imbiribeira | indefinido | Pessoas mexendo, tirando e colocando objetos na carroça | A wooden cart is present and stationary. People are observed interacting with the cart and the material. The volume of waste on the ground a |
| 89228777 | cam_imbiribeira | indefinido | Parecem apenas pessoas carregando um sofá para longe daquela região | Two individuals are interacting with a pile of debris on the ground near a cart or small vehicle. The pile of debris appears to be decreasin |
| c305f313 | cam_imbiribeira | indefinido | Pode ser que os indivíduos da van branca tenham realizado algum tipo de descarte | The scene shows a parked white van. A person is visible moving around the van and then walking away, but there is no clear indication of mat |
| d27584ab | cam_imbiribeira | indefinido | Pessoal que estava mexendo do caminhão e no lixo indo embora | The scene shows a road with a vehicle and a person near some orange equipment. The vehicle and person appear stationary. No active material  |
| dc908b80 | cam_mangabeira | indefinido | Trabalhador da prefeitura jogou um saco de lixo no local | A black car is parked near a pile of trash. Two individuals are observed interacting with the trash pile. In the final frame, one individual |
| e2d7dc4b | cam_imbiribeira | indefinido | Possível descarte ou coleta sendo realizada com uma carroça | A person is pushing a wooden cart (carroça) across the scene. A vehicle is stopped nearby. No material is being deposited or collected from  |
| ffdafc45 | cam_imbiribeira | indefinido | Possivel descarte sendo realizado por um homem | A wooden cart (carroça) is present and appears to be tipped over or being emptied. People are visible moving around the cart. The material o |

<!-- metrics-end -->

---

## Decisão

_(preenchida automaticamente — depende do resultado do PASS overall)_

## Caveats

- **Thinking budget fixado em 1024** nos 2 arms para isolar o efeito do prompt em si.
  Camp 09 (com mid_frames) mostrou que budget=0 dá mais recall que budget=2048 em V1;
  o sweet spot em 1024 foi escolhido para minimizar variância.
- **Mid frames inclusos** (3 frames em 25/50/75%) — reproduz fielmente o pipeline de
  produção (camp 08 alertou que first+last only não é representativo).
- **6 eventos `missed`** estão incluídos como positivos esperados. Produção atual não
  capturou nenhum deles; é razoável que V2 também não detecte sem dados de prior_window.
- **Carroças (11 eventos, 9 Indefinido)**: não pesam em PASS/FAIL, mas a tabela "Diffs
  por evento" mostra como cada arm trata. V2 NÃO deve auto-suprimir todos.

## Como reproduzir

```powershell
cd c:\saira
python benchmarks\campaigns\11-prompt-v2-promotion-2026-05-22\bench_prompt_v2_promotion.py `
  --campaign "benchmarks\campaigns\11-prompt-v2-promotion-2026-05-22\" `
  --arms A_current,B_v2_patched
python benchmarks\campaigns\11-prompt-v2-promotion-2026-05-22\compute_metrics.py
```

Para smoke test (1 TP + 1 FP + 1 baseline por arm, ~30s):

```powershell
python benchmarks\campaigns\11-prompt-v2-promotion-2026-05-22\bench_prompt_v2_promotion.py --smoke-test
```

## Artefatos

- `bench_prompt_v2_promotion.py` — runner adaptado de `bench_thinking_ab.py` (camp 09)
- `compute_metrics.py` — métricas + PASS evaluation + per-event flip table
- `results-{A_current,B_v2_patched}.json` — saída bruta por arm
- `metrics.json` — métricas computadas + decisão + flips
- `prompts/` — snapshots dos 4 prompts no momento do bench (gate/detail × current/v2)
- `run-config.yaml` — config canônico
- `report.md` — este arquivo

## Anotações

_(opcional — Fase 5 após review humano)_