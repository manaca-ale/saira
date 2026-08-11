# Estratégia de prompt — Claude Haiku 4.5 (Bedrock) como Agent-3 FP-screener

Síntese acionável do Deep Research **DR#1** (`pesquisas/dr1_haiku_fp_screener_prompt_2026-06-19.md`,
2026-06-19), já implementada em `scripts/screener_common.py` (`HAIKU_SYSTEM_PROMPT`,
`OUTPUT_JSON_SCHEMA`) e `scripts/run_screener.py` (`call_bedrock`).

## Técnicas adotadas (e por quê)

1. **Ancoragem temporal com tags XML `<frame>`** — em vez de despejar as imagens no fim do
   prompt, intercalar `<frame>Frame N: T=...</frame>` **antes de cada imagem**. Força o modelo
   a associar deltas visuais a estados temporais e a julgar a **mudança** (não descrever cada
   frame). É a principal defesa contra a confabulação "pessoa perto da pilha = descartou".
2. **System prompt persona-forense + `<rules>`** — papel de "validador final", regras explícitas
   dissociando *presença humana* de *mudança de estado da pilha*; catador que **leva** material
   ou pilha **inalterada/menor** ⇒ `false`.
3. **Recall guard assimétrico (regra de 15%)** — "rejeitar um descarte real degrada a malha de
   segurança; sob qualquer ambiguidade (oclusão, noite, ou se a chance de acúmulo novo > ~15%),
   o veredito positivo é obrigatório". Codificado também na **descrição do campo** `is_real_new_disposal`
   do schema (Haiku obedece regras de limiar embutidas no schema com alta fiabilidade).
4. **ROI crop da pile-zone** como frame final (bbox `[480,60,920,340]`, upscale 2×, ~1568px) —
   foca a geometria fina de sacolas pequenas, sem pagar tokens pela rua/prédios.
5. **Saída estruturada nativa `output_config` (json_schema)** — 100% de conformidade, sem regex.
   Fallback automático para JSON-em-prompt se a API rejeitar (`_HAIKU_USE_OUTPUT_CONFIG`).
6. **Extended thinking `budget_tokens=1024`** — ponto-ideal anti-alucinação para o julgamento
   sutil before/after; `max_tokens=2048` (folga p/ pensamento + JSON).

## Configuração Bedrock (`invoke_model`)

```python
payload = {
  "anthropic_version": "bedrock-2023-05-31",
  "system": HAIKU_SYSTEM_PROMPT,                 # persona-forense + <rules> + recall guard
  "max_tokens": 2048,
  "messages": [{"role":"user","content": [<frame_sequence> XML + imagens base64 + task]}],
  "output_config": {"format": {"type":"json_schema","schema": OUTPUT_JSON_SCHEMA}},
  "thinking": {"type":"enabled","budget_tokens":1024},
  # SEM temperature, SEM top_p, SEM assistant prefill (ver pitfalls)
}
```

## Pitfalls (DR#1) — todos evitados no código

- ❌ `temperature`/`top_p` **junto com** `output_config` em Claude 4.5+ → 400 ValidationException.
  (Só setamos `temperature` quando thinking está desligado.)
- ❌ **Assistant prefill** (`{"role":"assistant","content":"{"}`) → proscrito no Bedrock, anula o request.
- ❌ Faltar `additionalProperties: false` no schema → rejeição nativa. (Presente.)
- ❌ Imagens sem tags `<frame>` → perde o referencial temporal. (Intercalado.)
- ❌ `max_tokens` apertado vs `budget_tokens` → `stop_reason: max_tokens` (JSON truncado). (2048 >> 1024.)

## Resultado no benchmark (Camp 42)

Ver `report.md`/`metrics.json`. A questão central: o recall guard do Haiku preserva mais TPs que
o Gemini Flash (que perdeu 35/72)? E qual a supressão de FP de revira resultante?
