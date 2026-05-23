# Campanha 14 — V3.2 (collection-signal override, ≥2 signals) — 2026-05-23

> ❌ **FAIL** — V3 não atingiu os critérios: TP recall 31.2% < 35.0%, FP rate 22.6% > 21.42%, golden cases 0/3. Não promover. Escrever follow-up doc com próximos passos.

**Hipótese:** V3.2 mantém o gate de 2 sinais do V3 original (posture + handling)
MAS adiciona supressão quando >=2 sinais de collection-context aparecem
(scene=COLLECTION_OR_MAINTENANCE / municipal_equipment / flow=from_pile /
pile=decreased). Isso protege contra os 7 FPs de poda/limpeza municipal que
V3.1 ainda deixou passar, sem regredir o recall do V3 original (40%).

**Adicional V3.2:** prompt explica que cleaning crews também bend down, e que
bending sozinho não é dumping em cenas com rakes/brooms/uniformes.

**Bench reduzido:** 110 eventos + 8 baseline/série = 142 windows × 2 arms
(cobre os 3 goldens — índices 26, 92, 107 no manifest).

## Resultados

<!-- metrics-start -->

### Comparação A_v2_baseline vs B_v3_2_collection_fix

| Métrica | A_v2_baseline | B_v3_2_collection_fix | Δ (B-A) | Regra | Veredito |
|---------|----------------|----------------|----------|-------|----------|
| **TP recall total (%)** | 31.25 | 31.25 | +0.0pp | B >= 35.0% | ❌ |
|   delta vs A | — | +0.0pp | — | B-A >= 0.0pp | ✅ |
|   TP só catalogados | 35.71 | 35.71 | — | (informativo) | — |
|   Missed recall | 0.00 | 0.00 | — | — | — |
| **FP rate total (%)** | 16.98 | 22.64 | +5.7pp | B <= 21.42% | ❌ |
|   FP só catalogados | 20.27 | 29.73 | — | — | — |
|   FP em baseline | 9.38 | 6.25 | — | — | — |
| Indef trigger rate | 25.00 | 40.00 | — | informativo | — |
| Gate cost total (USD) | 0.10 | 0.12 | — | — | — |
| **Blended cost (USD)** | 0.24 | 0.30 | — | (informativo) | — |
| Latency p50 (ms) | 5115 | 4870 | — | — | — |
| Latency p95 (ms) | 14338 | 10381 | — | — | — |

### Golden cases (PASS criterion)

| Golden case | Esperado | B_v3 retornou | Veredito | Posture | Razão |
|-------------|----------|----------------|----------|---------|-------|
| 48350bb4 | ✅ detected | ❌ rejected (conf=0) | ❌ | passing_by | TP pano branco (descarte pedestre noturno) |
| 12506543 | ✅ detected | ❌ rejected (conf=0) | ❌ | collecting_from_pile | TP pedestre puro (3 homens) |
| d00a79bd | ✅ detected | ❌ rejected (conf=None) | ❌ | — | TP uniforme laranja |

### Por câmera

| Câmera | A TP recall | B TP recall | Δ | A FP rate | B FP rate | Δ |
|--------|--------------|--------------|----|------------|------------|----|
| cam_mangabeira | 44.4% (4/9) | 44.4% (4/9) | +0.0pp | 20.9% (9/43) | 34.9% (15/43) | +14.0pp |
| cam_imbiribeira | 14.3% (1/7) | 14.3% (1/7) | +0.0pp | 19.4% (6/31) | 22.6% (7/31) | +3.2pp |

### Distribuição de posture (V3)

| Posture (V3) | N windows |
|--------------|-----------|
| passing_by | 41 |
| depositing_at_pile | 32 |
| standing_near_pile | 24 |
| collecting_from_pile | 17 |
| absent | 13 |
| leaving_pile_area | 3 |

### Categorias do dataset

| Categoria | N |
|-----------|---|
| TP catalogados | 14 |
| Missed | 2 |
| FP catalogados | 74 |
| Baseline | 32 |
| Indefinido | 20 |

### Diffs por evento (V2 → V3)

#### ✅ TPs/Missed que V3 recuperou (V2 perdeu, V3 pegou) — DESEJADO (3 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 2bb892bc | cam_mangabeira | tp | Pessoas descartando restos de poda | leaving_pile_area | A person is observed bending down near the waste pile in frame 2, and then walking away from the pile without any visible object in frame 4. |
| 454c8308 | cam_imbiribeira | tp | Um homem realizando o descarte de lixo com um carrinho de mão | depositing_at_pile | A person in red is observed bending down near the pile of debris in multiple frames (08:55:50, 08:55:55). In earlier frames (08:55:35), the  |
| bc0528c2 | cam_mangabeira | tp | Um homem realizando o descarte do conteúdo de uma sacola branca | depositing_at_pile | A person in a red shirt is observed bending down near the pile with a white bag, and in a later frame, they are standing up holding the bag, |

#### 🔴 TPs/Missed que V3 perdeu (V2 pegava, V3 não) — REGRESSÃO (3 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 48350bb4 | cam_imbiribeira | tp | Dois homens descartando o conteúdo dentro de um grande saco/pano branco | passing_by | A person walks across the scene. A white truck is stopped in the middle ground. A white car is moving on the right. No dumping or collection |
| d00a79bd | cam_mangabeira | tp | Grande quantidade de lixo descartada por um homem utilizando uniforme laranja | — |  |
| d59d5309 | cam_mangabeira | tp | Um homem realizando o descarte utilizando um carrinho de mão | passing_by | The scene shows a pile of trash on the ground. A white car is present on the road and appears to be moving or parked briefly. Pedestrians ar |

#### 🟡 FPs/baseline novos do V3 (V2 rejeitava, V3 confirma) — REGRESSÃO (15 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 17ff7912 | cam_mangabeira | fp | Estavam realizando a poda | depositing_at_pile | A person in a blue shirt is seen bending down near the informal waste pile in multiple frames, appearing to handle material. The person then |
| 32c2f287 | cam_imbiribeira | fp | Veículos passando | leaving_pile_area | A person is observed carrying an object in frame 4 and walking away from the pile area without the object in frame 5, indicating dumping act |
| 3766dca1 | cam_mangabeira | fp | Estavam retirando o Lixo | depositing_at_pile | A person is observed interacting with the debris pile. In frame 2 (05:07:37), the person appears to be bending down and possibly carrying ma |
| 3e5cf0c6 | cam_imbiribeira | fp | Pessoal realizando a limpeza do local | leaving_pile_area | A person is observed walking towards the pile area carrying an object in earlier frames and is later seen walking away from the pile area wi |
| 4909dc2d | cam_imbiribeira | fp | Caminhão realizando a retirada de lixo | depositing_at_pile | A person is observed bending down near the waste pile while carrying an object (bag/debris) in the initial frames. In subsequent frames, the |
| 655ea4ae | cam_imbiribeira | fp | Apenas está chovendo | standing_near_pile | A vehicle with its cargo bed raised is stationary in multiple frames. A person is visible near the vehicle, appearing to handle material. Th |
| 66280d13 | cam_mangabeira | fp | Estavam limpando os restos de poda | depositing_at_pile | A person is observed bending down and carrying an object (bag) in earlier frames, and is seen with empty hands and walking away from the pil |
| 737fdbb7 | cam_mangabeira | fp | Caminhão estacionado | depositing_at_pile | A person is observed bending down and interacting with the ground near a pile of debris. The person appears to be depositing material, as in |
| b014d1e6 | cam_mangabeira | fp | Pessoas passando | depositing_at_pile | A person is seen bending down and handling a white bag, appearing to deposit material on the ground. The truck in the road is stopped for a  |
| b58f9b56 | cam_mangabeira | fp | Apenas um homem passando de bicicleta | depositing_at_pile | A person is seen pushing a cart towards the pile and then appears to be depositing material from the cart onto the ground. The pile visibly  |
| baseline | cam_imbiribeira | baseline |  | depositing_at_pile | A person in a red shirt is observed carrying an object towards the pile area in earlier frames and is later seen walking away from the pile  |
| d588e2b2 | cam_mangabeira | fp | Estavam realizando a poda | depositing_at_pile | A person is observed bending down near the trash pile while carrying an object, and then walking away with the object. This sequence, along  |
| e435c966 | cam_mangabeira | fp | Pessoas passando | depositing_at_pile | A person in a yellow shirt is observed bending down and handling material near the informal waste pile in frame 3. This posture, combined wi |
| e92728ca | cam_mangabeira | fp | Apenas motos passando | depositing_at_pile | A person on a motorcycle stops near the informal dump site. One person is seen carrying a yellow bag and appears to be interacting with the  |
| fc335631 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | depositing_at_pile | A person is observed bending down near the trash pile in multiple frames, carrying an object (bag/bundle) in earlier frames and appearing to |

#### ✅ FPs/baseline que V3 rejeitou (V2 confirmava, V3 rejeita) — DESEJADO (9 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 07925285 | cam_imbiribeira | fp | Pessoa passando com um carrinho | — |  |
| 1dd7f6e8 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | standing_near_pile | A black SUV is parked near the existing waste pile for several frames. A person is observed near the vehicle and the pile, but does not exhi |
| 2a619172 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | — |  |
| 38982b91 | cam_mangabeira | fp | Pessoas passando e pombos andando sobre o lixo | standing_near_pile | A person is observed walking on the sidewalk and then standing near an existing pile of debris. No material is being deposited or collected. |
| 8b1854b9 | cam_mangabeira | fp | Estavam retirando o Lixo | absent | A green truck with an open, raised cargo bed is stationary near the informal waste pile. Material from the pile appears to be loaded into th |
| 983dc78f | cam_mangabeira | fp | Pessoas passando | — |  |
| b114b248 | cam_imbiribeira | fp | Apenas pessoas e veículos passando | passing_by | A white car is parked in the scene for multiple frames. A person is observed walking in the background, moving away from the pile area. The  |
| baseline | cam_mangabeira | baseline |  | passing_by | The scene shows a pile of garbage on the side of the road. A white truck stops on the road in the later frames. People are seen walking on t |
| baseline | cam_mangabeira | baseline |  | absent | A white car is parked on the side of the road. No people are visible interacting with the trash pile. The trash pile appears to be pre-exist |

#### 🟡 Indef que V3 marcou (V2 não marcava) (6 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 3497125c | cam_imbiribeira | indefinido | Dois homens com uma carroça estão mexendo no lixo | depositing_at_pile | A person is observed bending down near the pile of debris in frames 4 and 5. While the exact transition of carrying an object to empty hands |
| 3f115960 | cam_imbiribeira | indefinido | Pessoas perto da carroça | depositing_at_pile | A person is seen bending down near the pile of debris in frame 3 (03:13:15) while interacting with a cart. The person's posture and proximit |
| 62894ccc | cam_imbiribeira | indefinido | Pessoas mexendo, tirando e colocando objetos na carroça | depositing_at_pile | A person in a red shirt is observed near a cart filled with debris. In the first frame, the cart is present but less full. In later frames,  |
| 89228777 | cam_imbiribeira | indefinido | Parecem apenas pessoas carregando um sofá para longe daquela região | depositing_at_pile | A person is observed near a pile of debris with a carroça. The person appears to be bending down and handling material, suggesting depositio |
| c305f313 | cam_imbiribeira | indefinido | Pode ser que os indivíduos da van branca tenham realizado algum tipo de descarte | depositing_at_pile | A person is observed walking towards the pile, then bending down and appearing to deposit material. The white van is stationary. The pile it |
| ffdafc45 | cam_imbiribeira | indefinido | Possivel descarte sendo realizado por um homem | depositing_at_pile | In the last frame, a person is seen near a tilted cart by the debris pile. The person appears to be handling material, and the cart's positi |

#### ✅ Indef que V3 parou de marcar (V2 marcava) (3 eventos)

| event_id | câmera | categoria | justificativa | V3 posture | V3 evidence |
|----------|---------|-----------|---------------|------------|-------------|
| 570a5967 | cam_mangabeira | indefinido | Possivelmente apenas uma pessoa passando com um carrinho de mão indo para uma re | absent | A blue truck is parked in the scene. A person in red is initially near the truck and then walks away. A white car stops near the pile of was |
| 85a764a7 | cam_imbiribeira | indefinido | Possível descarte ou coleta sendo realizada com uma carroça | passing_by | A person is observed near a pile of debris and a parked vehicle. The person moves away from the pile area across the frames. No material is  |
| d27584ab | cam_imbiribeira | indefinido | Pessoal que estava mexendo do caminhão e no lixo indo embora | standing_near_pile | A person and a vehicle are stationary near a large, permanent pile of debris. No clear evidence of material being deposited or removed is ob |

<!-- metrics-end -->