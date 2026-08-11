# Iterar o gate prompt do Arruda (esp32_005) — sessão de exploração

Quero **explorar e melhorar o prompt do gate (Agent-1)** da câmera **Arruda / esp32_005 /
cam_14**, que hoje perde descartes a pé / com carrinho de mão. Tenho liberdade pra testar
abordagens diferentes — o que vem abaixo é **contexto e ferramentas de uma sessão anterior,
NÃO um trilho fechado**. Questione minhas conclusões, proponha caminhos novos, mude o rumo se
fizer sentido. O objetivo final é capturar mais descarte real sem inflar falso positivo
(SAIRA pondera **recall ~3×**).

## O que eu já sei (provisório — pode contestar)
- **Arruda roda o gate V1** (`NEW_LITTER_SYSTEM_PROMPT`,
  `services/yolo-worker-vm/src/worker/detector_gemini.py:123`); o V3 só vale p/ esp32_001/002
  (`detector_gemini.py:815`). V1 ancora DUMPING em **veículo parado** → tende a perder
  descarte pedestre sutil.
- Tentativas anteriores **V3+B3** (Camp 34) e **V3+v2** (Camp 37) saíram **piores que o V1**
  no offline que eu tinha — mas esse offline era pobre, então não tome como veredito final.
  Há um prompt "do-zero" (`arruda_gate_from_scratch.md` / constante `SCRATCH` em
  `bench_scratch.py`) com um sinal promissor mas **inconclusivo (n=1)**: pegou 1 descarte que
  o V1 perdeu, com +1 FP. Use como ponto de partida OU descarte e comece de outro lugar.
- Ideias que pareceram importar pra discriminar (mas teste por conta própria): **PARAR no
  ponto** do muro à direita vs só passar; **direção do material** (p/ o chão = descarte; do
  monte p/ fora = coleta); exigir **prova positiva** de coleta (caminhão/uniforme/ferramenta/
  monte encolhendo) antes de classificar como coleta; baixa resolução (sinal pequeno/distante,
  vista ampla) → confiar em parar+manusear+sair, não em ver a pilha crescer.

## A virada metodológica (o que destrava testes de verdade)
- **A janela EXATA que o gate viu é recuperável** no audit log:
  `saira-yolo-worker-prod:/app/state/gemini_cascade_audit/{YYYY-MM-DD}/esp32_005.jsonl`
  (≈15 dias). Cada linha: `window_first_frame`, `window_last_frame`, `window_size`,
  `agent1_triggered/confidence`, `agent2_disposal`, `detection_id`. Reconstruindo a janela
  certa, o V1 reproduz ~9/11 das decisões de prod (com janela errada, reproduzia 0).
- **Dado limpo existe:** descartes confirmados no S3 e frames do volume vivo estão OK; só os
  exports do Drive dos eventos *perdidos* vinham corrompidos. **Frames purgam em ~1 dia**, então
  janelas exatas só dos últimos ~1-2 dias — dá pra acumular extraindo diariamente.

## Ferramentas (em `c:\saira`)
- Chave/modelo: `services/.env.benchmark` (`GEMINI_TEST_API_KEY`, projeto de teste). Prod roda
  `gemini-2.5-flash-lite`, thinking 2048, trigger `new_litter_detected AND confidence>=85`,
  5 frames (first+last+3 mid @25/50/75%) — replique isso pra ser fiel, **ou experimente
  variar** (mais frames? mosaico? outro modelo?) se achar que vale.
- Rodar um prompt: monkeypatch `worker._prompts_v3.NEW_LITTER_SYSTEM_PROMPT_V3 = <prompt>` +
  `analyze_new_litter_with_gemini(..., prompt_version="v3")`. Runner pronto: `bench_scratch.py`.
- Extrair janelas exatas de hoje: `tmp/extract_windows.sh` (lê um manifesto `LABEL|first|last|
  size` derivado do audit jsonl) puxa os 5 frames de cada janela do volume.
- Ground truth: status no DB (`saira-db-prod`, `psql -U postgres -d saira_db`,
  `detections WHERE camera_id=14`: CONFIRMADO/INDETERMINADO = descarte; REJEITADO = revisão
  derrubou) + a planilha humana "Mapeamento de Ocorrências"
  (`1wABg4qMYFR5IHG0lWlj0CBhL2jm5c_ARJQjdDXpvqko`, abas Capturadas / Não Capturadas).

## Bom senso (não regras rígidas)
- Compare contra V1 nas **mesmas janelas exatas**; reproduza conclusões ≥2× (modelo é
  não-determinístico); cuidado com overfit em amostra pequena — junte mais positivos rotulados
  antes de cravar. Offline é screen; a palavra final é validação ao vivo.

## Pontos de partida possíveis (escolha, combine ou ignore)
- Medir a variância do `SCRATCH` nas janelas de hoje (o ganho é real ou ruído?).
- Reescrever o prompt do zero com outra hipótese de discriminação.
- Acumular janelas exatas + rótulos por uns dias pra ter n>1.
- Tornar a reprodução bit-exata logando os 5 frames usados no `_audit_record` (`main.py`).
- Repensar se o lever certo é mesmo o gate, ou BGSUB / pile-crop / Agent-2.

Referências: campanha `benchmarks/campaigns/37-arruda-gate-addon-v2-2026-06-11/`; memórias
`project_camp37_...`, `project_camp34_...`, `project_gate_v1_onfoot_dump_fn`.
