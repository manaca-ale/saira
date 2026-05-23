# Campanha 12 — V3 (postura corporal) vs V2 (baseline) — 2026-05-22

> ❌ **FAIL** — V3 não atingiu os critérios: FP rate 39.5% > 21.42%, golden cases 2/3. Não promover. Escrever follow-up doc com próximos passos.

**Hipótese:** V3 (postura corporal como sinal primário + LOCAL_CONTEXT por câmera)
recupera os 4 TPs que V2 perdeu na camp 11 (d00a79bd uniforme, 48350bb4 pano
branco, a73a3f44 caminhonete, 2bb892bc poda) sem regredir as melhorias de V2 em
rejeição de coleta municipal.

**Modelos:**

- Gate: `gemini-2.5-flash-lite`
- Detail: `gemini-2.5-flash`
- Thinking budget: `1024` (fixo nos 2 arms)

**Arms:**

- A_v2_baseline: `prompt_version="v2"` (V2 com fix carroça da camp 11)
- B_v3_posture: `prompt_version="v3"` (V3 nova — postura como sinal primário)

**Dataset:** [data/datasets/official/](../../../data/datasets/official/) com
filtros idênticos à camp 11.

**Mudança principal V2 → V3:**

- Novo campo `person_position_signature` com 7 valores (depositing_at_pile,
  leaving_pile_area, approaching_pile, standing_near_pile, collecting_from_pile,
  passing_by, absent).
- Override positivo: posture in {depositing_at_pile, leaving_pile_area} +
  person_handling_material=True → DUMPING confirmado mesmo sem pile growth.
- Supressão por trânsito: posture=passing_by → forçar new_litter_detected=false.
- Texto explícito: "ABSENCE of pile growth is NOT evidence against dumping"
  (descartes de 0.01-0.15 m³ são invisíveis na resolução CCTV).
- LOCAL_CONTEXT por câmera populado direto no CAMERA_CONTEXT do bench (futura
  migration do DB).

---

## Resultados

<!-- metrics-start -->

### Comparação A_v2_baseline vs B_v3_posture

| Métrica | A_v2_baseline | B_v3_posture | Δ (B-A) | Regra | Veredito |
|---------|----------------|----------------|----------|-------|----------|
| **TP recall total (%)** | 25.00 | 40.00 | +15.0pp | B >= 35.0% | ✅ |
|   delta vs A | — | +15.0pp | — | B-A >= 0.0pp | ✅ |
|   TP só catalogados | 35.71 | 57.14 | — | (informativo) | — |
|   Missed recall | 0.00 | 0.00 | — | — | — |
| **FP rate total (%)** | 16.42 | 39.55 | +23.1pp | B <= 21.42% | ❌ |
|   FP só catalogados | 21.62 | 59.46 | — | — | — |
|   FP em baseline | 10.00 | 15.00 | — | — | — |
| Indef trigger rate | 25.00 | 60.00 | — | informativo | — |
| Gate cost total (USD) | 0.12 | 0.13 | — | — | — |
| **Blended cost (USD)** | 0.28 | 0.50 | — | (informativo) | — |
| Latency p50 (ms) | 5073 | 4953 | — | — | — |
| Latency p95 (ms) | 6758 | 12618 | — | — | — |

### Golden cases (PASS criterion)

| Golden case | Esperado | B_v3 retornou | Veredito | Posture | Razão |
|-------------|----------|----------------|----------|---------|-------|
| 48350bb4 | ✅ detected | ❌ rejected (conf=0) | ❌ | passing_by | TP pano branco (descarte pedestre noturno) |
| 12506543 | ✅ detected | ✅ detected (conf=85) | ✅ | depositing_at_pile | TP pedestre puro (3 homens) |
| d00a79bd | ✅ detected | ✅ detected (conf=90) | ✅ | depositing_at_pile | TP uniforme laranja |

### Por câmera

| Câmera | A TP recall | B TP recall | Δ | A FP rate | B FP rate | Δ |
|--------|--------------|--------------|----|------------|------------|----|
| cam_mangabeira | 30.8% (4/13) | 30.8% (4/13) | +0.0pp | 23.3% (10/43) | 62.8% (27/43) | +39.5pp |
| cam_imbiribeira | 14.3% (1/7) | 57.1% (4/7) | +42.9pp | 19.4% (6/31) | 54.8% (17/31) | +35.5pp |

### Distribuição de posture (V3)

| Posture (V3) | N windows |
|--------------|-----------|
| depositing_at_pile | 61 |
| passing_by | 39 |
| absent | 27 |
| standing_near_pile | 17 |
| leaving_pile_area | 11 |
| collecting_from_pile | 7 |
| approaching_pile | 1 |

### Categorias do dataset

| Categoria | N |
|-----------|---|
| TP catalogados | 14 |
| Missed | 6 |
| FP catalogados | 74 |
| Baseline | 60 |
| Indefinido | 20 |

### Diffs por evento (V2 → V3)

#### ✅ TPs/Missed que V3 recuperou (V2 perdeu, V3 pegou) — DESEJADO (5 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 12506543 | cam_imbiribeira | tp | Os dois homens ainda estavam mexendo no lixo, mas no final aparece um outro home | depositing_at_pile | A person is observed near a cart in the vicinity of the waste pile. In later frames, the person is no longer clearly visible, and the cart i |
| 218673e1 | cam_imbiribeira | tp | Dois homens realizando o descarte de objetos grandes | leaving_pile_area | A person is seen near the pile in the first frame carrying material and then walking away from the pile area in later frames without it, ind |
| a73a3f44 | cam_imbiribeira | tp | Caminhonete azul escura realiza o descarte de um grande volume de lixo | depositing_at_pile | A person is observed bending down near the large debris pile in the final frame, exhibiting a posture consistent with depositing material. A |
| bc0528c2 | cam_mangabeira | tp | Um homem realizando o descarte do conteúdo de uma sacola branca | depositing_at_pile | A person in a red shirt is observed bending and depositing material from bags onto the existing pile of waste. This posture and action are c |
| cb49921a | cam_imbiribeira | tp | Pessoas realizando o descarte do conteúdo de um saco marom aparentemente | depositing_at_pile | A person in a pink shirt is observed bending towards the pile in multiple frames (15:45:50, 15:46:05), indicating active depositing. A white |

#### 🔴 TPs/Missed que V3 perdeu (V2 pegava, V3 não) — REGRESSÃO (2 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 48350bb4 | cam_imbiribeira | tp | Dois homens descartando o conteúdo dentro de um grande saco/pano branco | passing_by | The scene shows people and vehicles moving through the area. No person is observed actively depositing or collecting material, nor is there  |
| d59d5309 | cam_mangabeira | tp | Um homem realizando o descarte utilizando um carrinho de mão | passing_by | A white car drives by on the road. Two pedestrians walk on the sidewalk, passing the informal waste pile without interaction. Later, a perso |

#### 🟡 FPs/baseline novos do V3 (V2 rejeitava, V3 confirma) — REGRESSÃO (40 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 10bfef31 | cam_mangabeira | fp | Estavam limpando os restos de poda | depositing_at_pile | Two individuals in green uniforms are present. One individual is consistently bending towards the ground/pile area across multiple frames, s |
| 13dc1453 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | depositing_at_pile | A person in a red shirt is observed near the debris pile in multiple frames, appearing to deposit material. A white car is also seen stopped |
| 17ff7912 | cam_mangabeira | fp | Estavam realizando a poda | depositing_at_pile | A person in a blue shirt is observed bending down near the informal waste pile in frame 2, then standing up and moving away in frame 3. This |
| 1a2c6dc6 | cam_imbiribeira | fp | Pessoas passando | depositing_at_pile | Two individuals are observed near the permanent waste pile. In the later frames, one individual is seen bending towards the ground near the  |
| 1c823d95 | cam_mangabeira | fp | Pessoa apenas estacionou e desceu com uma criança | depositing_at_pile | A person is seen exiting a parked car and approaching the informal waste pile. In the second frame, the person is standing near the pile, ho |
| 28fba845 | cam_mangabeira | fp | Pessoa passando com um carrinho | depositing_at_pile | Person observed approaching the informal waste pile, bending down to deposit material, and then walking away. Vehicle is stationary. The act |
| 3276c38a | cam_imbiribeira | fp | Apenas um cachorro andando | depositing_at_pile | A person is observed near a cart by a large pile of debris. The person appears to be interacting with the cart and the pile, consistent with |
| 32c2f287 | cam_imbiribeira | fp | Veículos passando | leaving_pile_area | A person is observed in the first frame appearing to carry an object and moving away from the pile area. In subsequent frames, the person is |
| 3766dca1 | cam_mangabeira | fp | Estavam retirando o Lixo | depositing_at_pile | A person approaches the informal pile, bends down as if depositing material, and then walks away. A truck is parked nearby. The pile volume  |
| 3c83eab7 | cam_mangabeira | fp | Apenas pessoas e veículos passando | leaving_pile_area | A person is observed near the pile in an earlier frame (14:08:40) and is seen walking away from the pile area in later frames (14:08:55, 14: |
| 4909dc2d | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | leaving_pile_area | A person is seen near a stationary truck with a raised cargo bed. The person appears to be unloading material from the truck onto the ground |
| 4b4f11d7 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | depositing_at_pile | A person is observed near the debris pile on the right side of the scene, exhibiting behavior consistent with depositing material. The perso |
| 4b6e9df1 | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | depositing_at_pile | A caminhão compactador EMLURB is stationary with its bed raised, and two individuals are present near it. The posture of the individuals and |
| 4ed80e61 | cam_mangabeira | fp | Pessoas passando | depositing_at_pile | A person in a blue shirt is seen in the final frame bending down near the ground with an object in hand, consistent with depositing material |
| 4f356133 | cam_mangabeira | fp | Estavam limpando os restos de poda | depositing_at_pile | A person in green is observed bending and reaching towards the ground/pile area in multiple frames, indicating active material deposition. A |
| 50e938ae | cam_imbiribeira | fp | Pessoas passando | depositing_at_pile | A white car is stopped near the large debris pile. Multiple individuals are observed near the car and the pile. One individual appears to be |
| 51a9ff0e | cam_mangabeira | fp | Estavam retirando o Lixo | depositing_at_pile | A truck with a raised cargo bed is stationary for multiple frames. A person in blue is observed near the truck, appearing to unload material |
| 655ea4ae | cam_imbiribeira | fp | Apenas está chovendo | depositing_at_pile | A carroceiro (person with cart) is present near the large debris pile. The carroceiro appears to be interacting with the pile or ground, con |
| 659c0d0d | cam_imbiribeira | fp | Apenas pessoas e veículos passando | depositing_at_pile | A person is observed near the debris pile, bending and reaching towards it in frame 4, indicating active depositing. The person remains in t |
| 66280d13 | cam_mangabeira | fp | Estavam limpando os restos de poda | depositing_at_pile | A person is observed approaching the informal waste pile, bending down to deposit material, and then leaving the immediate area. The pile vo |
| 737fdbb7 | cam_mangabeira | fp | Caminhão estacionado | depositing_at_pile | A person is observed squatting/bending near the informal waste pile in multiple frames (frames 1 and 3), consistent with depositing material |
| 765854fa | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | depositing_at_pile | A person in a red shirt is seen interacting with a detached red container on the ground near a stationary white truck. The person appears to |
| 767e7d17 | cam_imbiribeira | fp | Nada ocorrendo | depositing_at_pile | A person is observed bending down near the pile in the first frame, suggesting they are depositing material. The person is seen moving away  |
| 8afac80c | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | depositing_at_pile | A person in red is observed bending/squatting near the debris pile in frame 3 (20:37:15), suggesting they are depositing material. They are  |
| 8e92e6c3 | cam_mangabeira | fp | Estavam limpando os restos de poda | depositing_at_pile | A person in a green uniform is seen near a truck with a raised bed, actively unloading material onto the ground. The truck remains stationar |
| a018dd4d | cam_mangabeira | fp | Estavam limpando os restos de poda | depositing_at_pile | A person is seen bending down towards the informal waste pile, appearing to deposit material. A white van is stopped nearby on the road. The |
| a5db27cc | cam_mangabeira | fp | Estavam limpando os restos de poda | depositing_at_pile | A person in a green uniform is observed bending down near the informal waste pile in the first few frames, suggesting they are depositing ma |
| b014d1e6 | cam_mangabeira | fp | Pessoas passando | depositing_at_pile | A person is observed bending/squatting near the informal waste pile in multiple frames, handling material. In later frames, this person is s |
| b58f9b56 | cam_mangabeira | fp | Apenas um homem passando de bicicleta | depositing_at_pile | A person on a bicycle with a basket approaches the informal waste pile and appears to be depositing material. The person is near the pile, h |
| baseline | cam_imbiribeira | baseline |  | leaving_pile_area | A person is observed near the pile in the first frame and is seen walking away from the pile area in subsequent frames, consistent with leav |
| baseline | cam_imbiribeira | baseline |  | leaving_pile_area | A person is observed walking towards the pile area in the initial frames carrying an object, and then is seen walking away from the pile are |
| baseline | cam_mangabeira | baseline |  | depositing_at_pile | A person is seen approaching the pile carrying a white bag in frame 3. In subsequent frames, the person is no longer visible in that positio |
| baseline | cam_mangabeira | baseline |  | depositing_at_pile | A person is observed bending near the waste pile in frame 2, suggesting active depositing. The person is no longer visible near the pile in  |
| baseline | cam_mangabeira | baseline |  | depositing_at_pile | A person on a cart (carroça) is observed approaching the informal waste pile and is seen in the final frames bending over the pile, appearin |
| baseline | cam_mangabeira | baseline |  | depositing_at_pile | Person in green shirt is observed near the trash pile in multiple frames, with posture suggesting interaction with the pile. The person is h |
| baseline | cam_mangabeira | baseline |  | depositing_at_pile | A woman is observed approaching the pile with a bag, then positioned near the pile in a manner consistent with depositing material. A motorc |
| d588e2b2 | cam_mangabeira | fp | Estavam realizando a poda | depositing_at_pile | A person is observed bending and squatting near the informal waste pile, appearing to deposit material. The person is in this posture for mu |
| e92728ca | cam_mangabeira | fp | Apenas motos passando | depositing_at_pile | A motorcycle stops on the sidewalk near the informal dump. A passenger with a yellow bag dismounts and is seen bending towards the pile, app |
| f58d2688 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | depositing_at_pile | A person is observed bending/squatting near the existing pile of debris in frame 3 (13:01:30), indicating they are depositing material. This |
| fc335631 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | depositing_at_pile | A person is observed walking towards the pile of trash in the early frames and is seen very close to the pile in later frames, exhibiting a  |

#### ✅ FPs/baseline que V3 rejeitou (V2 confirmava, V3 rejeita) — DESEJADO (9 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 1dd7f6e8 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | passing_by | A black SUV is parked for the duration of the observation. A person is seen walking away from the vicinity of the parked vehicle and the exi |
| 2a619172 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | — |  |
| 5e3e79cd | cam_mangabeira | fp | Estavam retirando o Lixo | — |  |
| 8fd7e18e | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | absent | A white truck is parked in the scene. A person on a bicycle passes through. Another person in a red shirt is seen walking in the background. |
| b114b248 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | absent | A white car is parked in the scene for multiple frames. No person is actively depositing or collecting material. The pre-existing pile of de |
| baseline | cam_imbiribeira | baseline |  | passing_by | A person on a bicycle passes through the scene. No material is being deposited or collected. The large pile of debris remains unchanged. No  |
| baseline | cam_mangabeira | baseline |  | passing_by | A person is seen walking on the sidewalk in the last frame, moving away from the camera. No other individuals or vehicles are actively inter |
| baseline | cam_mangabeira | baseline |  | passing_by | A person is seen walking on the sidewalk, not interacting with the waste pile. A pickup truck passes by. No dumping or collection activity i |
| baseline | cam_mangabeira | baseline |  | standing_near_pile | The scene shows a pile of litter. A person is observed standing near the pile in one frame, and another person is walking on the road in lat |

#### 🟡 Indef que V3 marcou (V2 não marcava) (8 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 3497125c | cam_imbiribeira | indefinido | Dois homens com uma carroça estão mexendo no lixo | depositing_at_pile | Two individuals and a vehicle are present near the debris pile. One individual is bent over, suggesting they are depositing material. The ve |
| 3c60eccd | cam_imbiribeira | indefinido | Três homens mexendo em uma carroça, no lixo e queimando com fogo um objeto | depositing_at_pile | A person is observed near the debris pile on the left, appearing to bend or reach towards it in frames 1, 3, and 4. While the exact moment o |
| 3f115960 | cam_imbiribeira | indefinido | Pessoas perto da carroça | depositing_at_pile | A person is visible near a cart and the waste pile in multiple frames, appearing to bend or reach towards the ground/pile, consistent with d |
| 5b5dc924 | cam_imbiribeira | indefinido | Várias pessoas manuseando coisas no lixo e na caçamba de um caminhão | depositing_at_pile | Two individuals are observed near a parked truck and an excavator. One individual is seen bending down and appears to be depositing material |
| 62894ccc | cam_imbiribeira | indefinido | Pessoas mexendo, tirando e colocando objetos na carroça | depositing_at_pile | A person is observed near a cart filled with waste, interacting with the cart and the ground. This posture, combined with the presence of a  |
| 92968ee2 | cam_imbiribeira | indefinido | Possível descarte ou coleta sendo realizada com uma carroça | leaving_pile_area | A person is observed walking near the pile area in frames 3 and 4, and is no longer clearly visible in the same area in frame 5. This sugges |
| dc908b80 | cam_mangabeira | indefinido | Trabalhador da prefeitura jogou um saco de lixo no local | depositing_at_pile | A person is observed bending towards the pile of trash in frame 4 (13:41:31), consistent with depositing material. Another person is also pr |
| e2d7dc4b | cam_imbiribeira | indefinido | Possível descarte ou coleta sendo realizada com uma carroça | leaving_pile_area | A person is observed near a vehicle and a pile of debris in the first frame, and then walks away from the area in subsequent frames. The per |

#### ✅ Indef que V3 parou de marcar (V2 marcava) (1 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 570a5967 | cam_mangabeira | indefinido | Possivelmente apenas uma pessoa passando com um carrinho de mão indo para uma re | passing_by | The scene shows vehicles and a person moving through the area. A blue truck is present in the initial frames and then leaves. A white car ap |

<!-- metrics-end -->

---

## Decisão

_(preenchida automaticamente — depende do resultado do PASS overall)_

## Caveats

- **Thinking budget fixado em 1024** nos 2 arms para isolar o efeito do prompt
  V2 vs V3.
- **Mid frames inclusos** (3 frames em 25/50/75%) — mesmo padrão da camp 11.
- **LOCAL_CONTEXT hardcoded** no bench. Em produção esse campo virá da coluna
  `cameras.gemini_context_notes` (migração futura).
- **Camp 11 V2 baseline:** TP recall 25%, FP rate 16.42% (referência para PASS).
- **Camp 11 V1 prior baseline:** TP recall 35%, FP rate 33.58% — V3 ideal seria
  recuperar o recall do V1 mantendo FP rate do V2.

## Como reproduzir

```powershell
cd c:\saira
python benchmarks\campaigns\12-prompt-v3-posture-2026-05-22\bench_prompt_v3_posture.py `
  --arms A_v2_baseline,B_v3_posture --baseline-per-series 15
python benchmarks\campaigns\12-prompt-v3-posture-2026-05-22\compute_metrics.py
```

Smoke test (~30s, 1 TP + 1 FP + 1 baseline por arm):

```powershell
python benchmarks\campaigns\12-prompt-v3-posture-2026-05-22\bench_prompt_v3_posture.py --smoke-test
```

## Artefatos

- `bench_prompt_v3_posture.py` — runner adaptado de camp 11
- `compute_metrics.py` — métricas + PASS + per-event flip table V2→V3
- `results-{A_v2_baseline,B_v3_posture}.json` — saída bruta
- `metrics.json` — métricas + decisão + flips + posture distribution
- `prompts/` — snapshots dos 4 prompts (gate/detail × v2/v3)
- `run-config.yaml` — config canônico
- `report.md` — este arquivo