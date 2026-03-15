"""
organize_data.py — Reorganiza datasets e resultados de teste SAIRA
Moves data from c:\saira\tmp\ to c:\saira\data\ with a structured hierarchy.

Usage:
    python services/scripts/organize_data.py --dry-run   # preview only
    python services/scripts/organize_data.py             # execute moves
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("c:/saira")
TMP = ROOT / "tmp"
DATA = ROOT / "data"

# ---------------------------------------------------------------------------
# Move spec: (src_relative_to_tmp, dst_relative_to_data, metadata)
# ---------------------------------------------------------------------------
MOVES = [
    # ---- DATASETS: field CCTV ----
    (
        "global_test/staging_field",
        "datasets/field_cctv",
        {
            "type": "dataset",
            "category": "field_cctv",
            "description": "Clips CCTV de campo com infrações confirmadas (BOA_VISTA, foto, ID)",
            "notes": "foto_39_a_42 excluído dos testes por payload atípico (>8MB/janela)",
        },
    ),
    # ---- DATASETS: ESP32 sem ocorrência ----
    (
        "global_test/sem_staging",
        "datasets/esp32_sem_ocorrencia/sem_staging",
        {
            "type": "dataset",
            "category": "esp32_sem_ocorrencia",
            "description": "Subset curado de capturas ESP32 sem infração (dados limpos para regressão)",
        },
    ),
    (
        "global_test/sem_staging_night",
        "datasets/esp32_sem_ocorrencia/sem_staging_night",
        {
            "type": "dataset",
            "category": "esp32_sem_ocorrencia",
            "description": "Variante noturna do subset sem infração",
        },
    ),
    # ---- DATASETS: ESP32 com ocorrência ----
    (
        "global_test/ocorrencias_staging",
        "datasets/esp32_ocorrencias/ocorrencias_staging",
        {
            "type": "dataset",
            "category": "esp32_ocorrencias",
            "description": "Capturas ESP32 com infrações confirmadas (subset curado de occurrence_logs)",
        },
    ),
    # ---- DATASETS: janela horária 14-15h ----
    (
        "global_test/staging_1400_1500",
        "datasets/esp32_sem_ocorrencia/staging_1400_1500",
        {
            "type": "dataset",
            "category": "esp32_sem_ocorrencia",
            "description": "Subset por janela horária 14h-15h (esp32_001-005)",
        },
    ),
    # ---- RESULTADOS: 2026-03-11 ----
    (
        "test_logs/benchmark",
        "test_results/2026-03-11/benchmark",
        {
            "type": "test_result",
            "date": "2026-03-11",
            "prompt_version": "v0_baseline",
            "model": "gemini-2.5-flash",
            "description": "Cascade benchmark10 — 51 runs nos 3 dispositivos",
        },
    ),
    (
        "test_logs/consistency",
        "test_results/2026-03-11/consistency",
        {
            "type": "test_result",
            "date": "2026-03-11",
            "prompt_version": "v0_baseline",
            "model": "gemini-2.5-flash",
            "description": "Testes de consistência lite/mosaic/prefilter (60+ runs)",
        },
    ),
    (
        "test_logs/validation",
        "test_results/2026-03-11/validation",
        {
            "type": "test_result",
            "date": "2026-03-11",
            "prompt_version": "v0_baseline",
            "model": "gemini-2.5-flash",
            "description": "Validação r10/r11/r12 com diferentes configurações",
        },
    ),
    (
        "test_logs/serial",
        "test_results/2026-03-11/serial",
        {
            "type": "test_result",
            "date": "2026-03-11",
            "prompt_version": "v0_baseline",
            "model": "gemini-2.5-flash",
            "description": "Serial tests esp-001 (3 runs, até 2h de duração)",
        },
    ),
    # ---- RESULTADOS: 2026-03-12 ----
    (
        "test_logs/local_platform",
        "test_results/2026-03-12/smoke_local",
        {
            "type": "test_result",
            "date": "2026-03-12",
            "prompt_version": "v0_baseline",
            "model": "gemini-2.5-flash",
            "description": "Testes de plataforma local (3 runs cascade em esp32_001)",
        },
    ),
    # ---- RESULTADOS: 2026-03-13 ----
    (
        "test_logs_flash",
        "test_results/2026-03-13/cascade_retest_flash",
        {
            "type": "test_result",
            "date": "2026-03-13",
            "prompt_version": "v0_baseline",
            "model": "gemini-2.5-flash",
            "description": "Retest flash (130K JSONL) — primeira rodada completa",
        },
    ),
    (
        "test_logs/cascade",
        "test_results/2026-03-13/cascade_retest_iteracoes",
        {
            "type": "test_result",
            "date": "2026-03-13",
            "prompt_version": "v0_baseline",
            "model": "gemini-2.5-flash",
            "description": "Iterações de retest cascade (6 JSONL, exploração de configurações)",
        },
    ),
    # ---- RESULTADOS: 2026-03-14 ----
    (
        "tp_test_results",
        "test_results/2026-03-14/baseline_tp",
        {
            "type": "test_result",
            "date": "2026-03-14",
            "prompt_version": "v1_gate_only",
            "model": "gemini-2.5-flash",
            "gate_threshold": 75,
            "dataset": "esp32_ocorrencias",
            "description": "True positive baseline (prompt v1, antes das correções comportamentais)",
        },
    ),
    (
        "fp_test_results",
        "test_results/2026-03-14/baseline_fp",
        {
            "type": "test_result",
            "date": "2026-03-14",
            "prompt_version": "v1_gate_only",
            "model": "gemini-2.5-flash",
            "gate_threshold": 75,
            "dataset": "esp32_sem_ocorrencia",
            "description": "False positive baseline (prompt v1, antes das correções comportamentais)",
        },
    ),
    (
        "tp_esp32_001_results",
        "test_results/2026-03-14/tp_esp32_001_v1",
        {
            "type": "test_result",
            "date": "2026-03-14",
            "prompt_version": "v1_gate_only",
            "model": "gemini-2.5-flash",
            "dataset": "esp32_001_subset",
            "description": "TP esp32_001 — iteração v1",
        },
    ),
    (
        "tp_esp32_001_results_v2",
        "test_results/2026-03-14/tp_esp32_001_v2",
        {
            "type": "test_result",
            "date": "2026-03-14",
            "prompt_version": "v1_gate_only",
            "model": "gemini-2.5-flash",
            "dataset": "esp32_001_subset",
            "description": "TP esp32_001 — iteração v2",
        },
    ),
    (
        "global_test/results_field",
        "test_results/2026-03-14/field_v1_prompt_base",
        {
            "type": "test_result",
            "date": "2026-03-14",
            "prompt_version": "v1_gate_only",
            "model": "gemini-2.5-flash",
            "gate_threshold": 75,
            "dataset": "field_cctv",
            "description": "Campo v1 — prompt baseline sem behavioral context. 9 infrações / 117 janelas.",
            "infractions_confirmed": 9,
            "datasets_detected": 6,
        },
    ),
    (
        "global_test/results_field_v2",
        "test_results/2026-03-14/field_v2_prompt_fix",
        {
            "type": "test_result",
            "date": "2026-03-14",
            "prompt_version": "v2_behavioral_context",
            "model": "gemini-2.5-flash",
            "gate_threshold": 75,
            "dataset": "field_cctv",
            "description": "Campo v2 — Behavioral Context Check (Pattern A+B) + Agent2 relaxado. 15 infrações / 117 janelas.",
            "infractions_confirmed": 15,
            "datasets_detected": 9,
            "changes": [
                "Gate: BEHAVIORAL CONTEXT CHECK step (4) com Pattern A e Pattern B",
                "Agent2: aceita objeto novo pesado/volumoso sem exigir infrator visível",
            ],
        },
    ),
    (
        "global_test/results_ocorrencias",
        "test_results/2026-03-14/esp32_ocorrencias",
        {
            "type": "test_result",
            "date": "2026-03-14",
            "prompt_version": "v1_gate_only",
            "model": "gemini-2.5-flash",
            "gate_threshold": 75,
            "dataset": "esp32_ocorrencias",
            "description": "Teste em capturas ESP32 com ocorrências confirmadas",
        },
    ),
    (
        "global_test/results_sem_night",
        "test_results/2026-03-14/esp32_sem_night",
        {
            "type": "test_result",
            "date": "2026-03-14",
            "prompt_version": "v1_gate_only",
            "model": "gemini-2.5-flash",
            "gate_threshold": 75,
            "dataset": "esp32_sem_ocorrencia",
            "description": "Regressão sem imagens noturnas (462K JSONL)",
        },
    ),
    (
        "global_test/results_1400_1500",
        "test_results/2026-03-14/esp32_janela_1400_1500",
        {
            "type": "test_result",
            "date": "2026-03-14",
            "prompt_version": "v1_gate_only",
            "model": "gemini-2.5-flash",
            "gate_threshold": 75,
            "dataset": "esp32_staging_1400_1500",
            "description": "Teste com janela horária 14h-15h",
        },
    ),
    # ---- OCCURRENCE LOGS: prod ----
    (
        "occurrence_logs/saira_occurrence_logs_prod_20260313_064520",
        "occurrence_logs/prod/2026-03-13_064520",
        {
            "type": "occurrence_log",
            "env": "prod",
            "date": "2026-03-13",
            "time": "06:45:20",
        },
    ),
    (
        "occurrence_logs/saira_occurrence_logs_prod_20260313_082049",
        "occurrence_logs/prod/2026-03-13_082049",
        {
            "type": "occurrence_log",
            "env": "prod",
            "date": "2026-03-13",
            "time": "08:20:49",
        },
    ),
    (
        "occurrence_logs/saira_occurrence_logs_prod_20260314_055550",
        "occurrence_logs/prod/2026-03-14_055550",
        {
            "type": "occurrence_log",
            "env": "prod",
            "date": "2026-03-14",
            "time": "05:55:50",
        },
    ),
    # ---- OCCURRENCE LOGS: test (completos com uploads) ----
    (
        "occurrence_logs/saira_occurrence_logs_test_20260313_082049",
        "occurrence_logs/test/2026-03-13_082049",
        {
            "type": "occurrence_log",
            "env": "test",
            "date": "2026-03-13",
            "time": "08:20:49",
            "size_estimate": "3.1G",
            "has_uploads": True,
            "description": "Run completo com uploads esp32_001-005 (inclui sem_ocorrencia/)",
        },
    ),
    (
        "occurrence_logs/saira_occurrence_logs_test_20260314_055550",
        "occurrence_logs/test/2026-03-14_055550",
        {
            "type": "occurrence_log",
            "env": "test",
            "date": "2026-03-14",
            "time": "05:55:50",
            "size_estimate": "7.3G",
            "has_uploads": True,
            "description": "Run completo com uploads esp32_001-005 (inclui sem_ocorrencia/)",
        },
    ),
    # ---- OCCURRENCE LOGS: test (parciais / vazios de 2026-03-12) ----
    (
        "occurrence_logs/saira_occurrence_logs_test_20260312_173258",
        "occurrence_logs/test/2026-03-12/173258",
        {"type": "occurrence_log", "env": "test", "date": "2026-03-12", "has_uploads": False},
    ),
    (
        "occurrence_logs/saira_occurrence_logs_test_20260312_173648",
        "occurrence_logs/test/2026-03-12/173648",
        {"type": "occurrence_log", "env": "test", "date": "2026-03-12", "has_uploads": False},
    ),
    (
        "occurrence_logs/saira_occurrence_logs_test_20260312_202136",
        "occurrence_logs/test/2026-03-12/202136",
        {"type": "occurrence_log", "env": "test", "date": "2026-03-12", "has_uploads": False},
    ),
    (
        "occurrence_logs/saira_occurrence_logs_test_20260312_212916",
        "occurrence_logs/test/2026-03-12/212916",
        {"type": "occurrence_log", "env": "test", "date": "2026-03-12", "has_uploads": False},
    ),
    (
        "occurrence_logs/saira_occurrence_logs_test_20260313_064520",
        "occurrence_logs/test/2026-03-13_064520",
        {"type": "occurrence_log", "env": "test", "date": "2026-03-13", "has_uploads": False},
    ),
]

# Directories to SKIP (not moved, flagged for manual review)
SKIP = [
    # Empty occurrence log runs — no useful data
    "occurrence_logs/saira_occurrence_logs_test_20260312_170224",
    "occurrence_logs/saira_occurrence_logs_test_20260312_172037",
    "occurrence_logs/saira_occurrence_logs_test_20260312_172104",
    "occurrence_logs/saira_occurrence_logs_test_20260312_173400",
    # Smoke tests — minimal, no analytic value
    "occurrence_logs_smoke",
    "occurrence_logs_smoke2",
    "occurrence_logs_smoke3",
    "occurrence_logs_smoke4",
    "occurrence_logs_uploadtest",
    # frames/ — redundant with staging_field (already moved above)
    # frames_deteccao_20260313 — redundant with ocorrencias_staging
    # regression_v2 — empty JSONL, test in progress
    "regression_v2",
    # misc test_logs subdirs (not test results, just scratch)
    "test_logs/misc",
    "test_logs/cost",
    "test_logs/optimization",
    "test_logs/live",
    "test_logs/telegram",
    "test_logs/datasets",
]

# Directories left in tmp intentionally (active work)
LEAVE_IN_TMP = [
    "regression_v2",          # active regression test in progress
    "frames",                 # review before deleting (may overlap staging_field)
    "frames_deteccao_20260313",  # review before deleting (may overlap ocorrencias_staging)
    "Ref Campo",              # reference material — keep accessible
    "saira-model-training-setup",  # training setup — separate concern
    "dataset_002_003_005",    # small sample, keep for quick tests
    "dataset_esp32_001_0750_0757",  # small sample, keep for quick tests
]


def log(msg: str, dry_run: bool) -> None:
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}{msg}")


def move_dir(src: Path, dst: Path, dry_run: bool) -> bool:
    """Move src directory to dst. Returns True on success."""
    if not src.exists():
        print(f"  SKIP (not found): {src}")
        return False
    if dst.exists():
        print(f"  SKIP (already exists at dst): {dst}")
        return False
    log(f"  MOVE  {src.relative_to(ROOT)}  ->  {dst.relative_to(ROOT)}", dry_run)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(dst))
        except (PermissionError, OSError) as e:
            print(f"  ERROR moving {src.name}: {e}")
            # Clean up partial destination if created
            if dst.exists() and not any(dst.iterdir()):
                dst.rmdir()
            return False
    return True


def write_metadata(dst: Path, meta: dict, dry_run: bool) -> None:
    meta_path = dst / "metadata.json"
    meta["_organized_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    log(f"  META  {meta_path.relative_to(ROOT)}", dry_run)
    if not dry_run:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Organize SAIRA datasets and test results.")
    parser.add_argument("--dry-run", action="store_true", help="Preview moves without executing.")
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    print(f"\n=== SAIRA Data Organizer {'(DRY RUN)' if dry_run else ''} ===")
    print(f"  Source : {TMP}")
    print(f"  Dest   : {DATA}\n")

    if not TMP.exists():
        sys.exit(f"ERROR: tmp directory not found: {TMP}")

    if not dry_run:
        DATA.mkdir(parents=True, exist_ok=True)

    moved = 0
    skipped = 0

    for src_rel, dst_rel, meta in MOVES:
        src = TMP / src_rel
        dst = DATA / dst_rel
        ok = move_dir(src, dst, dry_run)
        if ok:
            write_metadata(dst, meta, dry_run)
            moved += 1
        else:
            skipped += 1

    print(f"\n--- Skipped (empty/smoke/redundant) ---")
    for rel in SKIP:
        p = TMP / rel
        status = "exists" if p.exists() else "not found"
        print(f"  SKIP  {rel}  ({status})")

    print(f"\n--- Left in tmp (active/review) ---")
    for rel in LEAVE_IN_TMP:
        p = TMP / rel
        status = "exists" if p.exists() else "not found"
        print(f"  KEEP  {rel}  ({status})")

    print(f"\n=== Summary ===")
    print(f"  Moved   : {moved}")
    print(f"  Skipped : {skipped}")
    if dry_run:
        print("\nRun without --dry-run to execute.")
    else:
        print(f"\nData organized at: {DATA}")


if __name__ == "__main__":
    main()
