# V2 — evidencia exigida so para INTERAGENTE_CURTA (patch sobre E+CROPS deployado)

Base = DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS (deployado). Patch (override PASSO 4):

Para INTERAGENTE_CURTA (3-30s sem postura especial), exigir PELO MENOS UMA evidencia
concreta de transferencia p/ infraction_confirmed=true: (a) maos cheias->vazias na pilha,
(b) objeto novo nos CROPS fim-vs-inicio, ou (c) mudanca de carga de carrinho/veiculo. Sem
nenhuma -> false. AGACHADA_LONGA e PAUSADA seguem DEFAULT-CON. Campo novo: crop_new_object.

Hipotese: ataca a confabulacao "INTERAGENTE_CURTA -> inventa deposito" preservando os casos
de postura longa (recall).
