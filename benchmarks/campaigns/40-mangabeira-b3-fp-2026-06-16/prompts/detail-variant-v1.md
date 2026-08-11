# V1 — transient-return crop-grounded (patch sobre E+CROPS deployado)

Base = DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS (deployado). Patch acrescentado:

AP8 — PASSANTE CONFIRMADO POR CROP: Se uma pessoa muda de posicao em TODOS os frames
(trajetoria linear, SEM dwell de 4+ frames consecutivos na frente da pilha) E os CROPS
da pile-zone NAO mostram nenhum objeto novo no fim vs inicio, entao ela e PASSANTE ->
infraction_confirmed=false, MESMO que carregue uma sacola momentanea em 1-2 frames. Esta
regra TEM PRECEDENCIA sobre "delta nao exigido" quando a pessoa nunca para na pilha.
Campo novo no JSON: crop_new_object (bool).

Hipotese: corta transeunte/trafego (B3) sem tocar AGACHADA_LONGA/PAUSADA (recall tiny-bag).
