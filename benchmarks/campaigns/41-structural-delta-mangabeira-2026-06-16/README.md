# Camp 41 — Structural-delta para o Mangabeira

Valida (Fase 1, offline $0) e integra no worker EC2 (Fase 2, shadow) detecção de mudança
**estrutural** (Census-Hamming + micro-tiles, before/after) para separar descarte real de
falso-positivo "transeunte" no esp32_002. Ver `report.md` para o resultado completo.

**TL;DR:** GATE PASSOU. `census_ntiles_t32` (first-vs-last) AUC 0,827 com **holdout temporal
estável** — a 1ª alavanca de visão que separa TP/B3 no Mangabeira sem colapsar (≠ DINOv2). Papel
= veto de FP em shadow. `detector_structural.py` no worker, 137 testes passam.

## Pipeline (reproduzir)
```bash
cd c:/saira
python benchmarks/campaigns/41-.../scripts/extract_before_after.py        # motion-picked
python benchmarks/campaigns/41-.../scripts/make_firstlast.py              # first-vs-last (vencedor)
python benchmarks/campaigns/41-.../scripts/phase_struct_signals.py _firstlast
python benchmarks/campaigns/41-.../scripts/phase_struct_roc.py _firstlast
python benchmarks/campaigns/41-.../scripts/verify_checks.py               # montagens + repro camp20
```

## Worker (Fase 2)
- `services/yolo-worker-vm/src/worker/detector_structural.py` + config `STRUCTURAL_*` + seam em `main.py`.
- Paridade: `cd services/yolo-worker-vm/src && STRUCTURAL_FILTER_MODE=shadow python -c "from worker import detector_structural"`.
- Deploy: `STRUCTURAL_FILTER_MODE=shadow STRUCTURAL_DEVICES=esp32_002` no `.env` de prod, rebuild+recriar worker.
