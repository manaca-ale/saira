# Plano — Veto estrutural (Census-Hamming) no gate da Pi

## Contexto / motivação
A pesquisa `aod-persistent-pile-outdoor.md` mostra que o gate atual da Pi (MOG2 por
**intensidade**) é o método que ela classifica como **obsoleto para outdoor**: dispara em
sombra dura móvel, surta no switch IR ao anoitecer, e perde saco escuro em asfalto escuro
(Δfg≈0). Observamos isso ao vivo em 2026-06-18: após restringir o polígono à calçada, os
eventos da rua sumiram mas sobraram ~1,5/min de **sombra/micro-movimento** (fg 220–470,
delta 450–470).

A receita da pesquisa = **Census Transform + Hamming em micro-tiles** sobre uma referência
pré-evento congelada (invariante a brilho → ignora sombra/IR; barato no Cortex-A53 via
XOR/popcount). Isso **já existe validado no projeto**: a **Camp 41**
(`services/yolo-worker-vm/src/worker/detector_structural.py`), que sobrevive a holdout
temporal (train AUC 0,832 → test 0,826) — mas roda só na **nuvem (worker)** como veto de FP
pós-detail. O gap é levar essa verificação para a **borda (Pi)**, onde corta o evento antes
do 4G/Gemini.

## Objetivo
Adicionar um **veto estrutural no fechamento do evento** na Pi: comparar Ref_Pre × Ref_Post
(que a Pi já captura) por Census-Hamming em tiles dentro do polígono; se a mudança for só
iluminação/sombra (poucos tiles mudados), **não sobe pro Gemini**. Substitui o filtro
transiente por intensidade (`PI_EVENT_MIN_RESIDUAL_PX`) por um **invariante a iluminação**.

## Componentes
1. **Novo módulo `census_delta.py`** na Pi (`services/raspberry-pi/agent/`), espelhando a
   lógica de `detector_structural.py`:
   - `_census_transform(gray)` (3×3 → uint8), `_census_hamming(pre, post)` (0..8 por pixel),
     `count_changed_tiles(pre, post, mask, tile=32, ham_thr, tile_frac=0.5)` → `n_tiles_changed`
     (= `census_ntiles_t32` da Camp 41).
   - Reusa a **máscara do polígono** já existente em `motion_gate._zone_mask` e o frame
     **reduzido** (a decodificação `IMREAD_REDUCED_COLOR_2` já roda no gate). Só numpy/cv2 —
     **sem dep nova**, sem GPU.
2. **Inputs:** `Ref_Pre` = frame pré-evento congelado (`_frame_ring[0]`, que a Pi já manda
   como "antes"); `Ref_Post` = frame do `end`. Ambos cinza, recortados à bbox da zona.
3. **Integração** no ramo `end` de `saira_agent._capture_once` (onde hoje está o filtro
   transiente, [saira_agent.py:290-309](../services/raspberry-pi/agent/saira_agent.py#L290)):
   - `n = count_changed_tiles(pre, post, mask)`.
   - `n < PI_STRUCTURAL_THRESHOLD` → **veto** (marca `end_transient` → worker descarta sem
     Gemini, OU não enfileira o lote). Senão → sobe normal.
4. **Flag de modo** (espelha `STRUCTURAL_FILTER_MODE` da Camp 41): `PI_STRUCTURAL_VETO`
   = `off | shadow | on`.
   - `shadow`: **computa e LOGA** `n_tiles_changed` por evento (+ se *vetaria*), mas **não veta**
     — para validação.
   - `on`: aplica o veto.
   - Params: `PI_STRUCTURAL_TILE=32`, `PI_STRUCTURAL_HAM_THR`, `PI_STRUCTURAL_TILE_FRAC=0.5`,
     `PI_STRUCTURAL_THRESHOLD` (começar no `thr=2` da Camp 41).
5. **Guarda de IR-switch** (Fase 1 da pesquisa; para o anoitecer): monitorar o delta de
   luminância global entre frames; num spike massivo (assinatura do filtro IR), **resetar o
   Ref_Pre + suprimir gatilhos ~10s** até a auto-exposição estabilizar. Evita a cascata de FP
   no dusk. *(Pode ser fase 2.)*

## Validação (disciplina Camp 41 — antes de enforce)
1. Deploy em **`shadow`** primeiro (no stack de teste, onde a `pi-cam-001` já roda).
2. Coletar **≥1 dia inteiro** — precisa incluir a manhã (sombra móvel) **e o switch IR ao
   anoitecer**.
3. Confirmar separação: eventos de sombra/iluminação → `n_tiles_changed` baixo; depósitos/
   pessoa-com-objeto → alto. Tirar o threshold do ROC (prior = thr 2).
4. **Cross-check com o Gemini**: o worker já classifica CON/REJ — confirmar que o veto só
   derruba eventos que o Gemini **também** rejeitou (zero perda de TP).
5. Só então flipar para **`on`**.

## Riscos / notas
- **Qualidade do Ref_Pre:** congelado no início do evento (a Pi já faz). Se o evento abrir
  tarde, o delta pode subestimar — mesma limitação de hoje.
- **Recall:** depósito real de baixíssimo contraste pode gerar poucos tiles (Census pega
  estrutura melhor que intensidade, mas não é mágica). Começar conservador + validar contra
  os CON do Gemini.
- **Por-câmera:** os thresholds da Camp 41 foram do Mangabeira (cam_11); a `pi-cam-001` é
  outra cena → revalidar em `shadow` mode aqui.
- **Custo Pi 3:** roda **só no fechamento do evento** (não por frame), num recorte pequeno
  da zona, reduzido → XOR/popcount é barato. Sem impacto térmico relevante.

## Esforço / deploy
Mesmo padrão do batch-upload: 1 módulo novo + integração no `_capture_once` + flag + campanha
de validação. Deploy na Pi por cópia de arquivo + flag no `.env` (reversível: `off`).
