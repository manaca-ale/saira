#!/usr/bin/env python3
"""Campaign 38b — ARRUDA_V2 (shortened) detail prompt, 2 reps fixed.

Fixes vs Camp 38 ARRUDA arm: ~3x shorter camera addendum + explicit conciseness
instruction (kills the JSON-truncation failure) + slightly softer positive-proof
(protect CONF recall). Target: REJ confirm <= 50% AND CONF confirm >= 9/10.
"""
from __future__ import annotations
import glob, os, sys, types, uuid, json, time
from pathlib import Path

ROOT = Path(r"c:\saira")
WORKER_SRC = ROOT / "services" / "yolo-worker-vm" / "src"
CAMP = Path(__file__).parent
CORPUS = ROOT / "tmp" / "arruda_detail_corpus"
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
if not os.environ.get("GEMINI_API_KEY"):
    for line in (ROOT / "services" / ".env.benchmark").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("GEMINI_TEST_API_KEY") and "=" in line:
            os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip(); break
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://stub@localhost/stub")
os.environ.setdefault("GEMINI_MODEL", "gemini-2.5-flash")
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
sys.modules.setdefault("cv2", types.SimpleNamespace())
from worker import detector_gemini as dg  # noqa: E402

STATUS = {
    "01c9e4c7": "CONF", "6834dad7": "CONF", "01e54259": "CONF", "9085ad0e": "CONF",
    "d7822b53": "CONF", "bcb8038c": "CONF", "a5a72209": "CONF", "ce13f76c": "CONF",
    "6328e4e6": "CONF", "50c32313": "CONF",
    "8657dafd": "COLETA",
}
INDET = {"b797daa9", "95dd7824", "bd466bda", "6e2e95ce", "6a126950", "9e112c6d",
         "4d51d0a1", "0c4976c0", "f7913b02", "0f2e9b60", "0cb3394b"}
REJ_IDS = {os.path.basename(p)[:8] for p in glob.glob(str(ROOT / "tmp" / "det_frames_rej" / "*.json"))}

ARRUDA_CTX = {
    "device_id": "esp32_005", "camera_name": "ESP32-005 - Arruda",
    "logradouro": "Arruda", "bairro": "Arruda", "rpa": "RPA 2",
    "gemini_context_notes": (
        "Câmera elevada sobre via asfaltada de mão dupla, vista AMPLA e distante. À DIREITA, "
        "encostado num muro, há um PONTO CRÔNICO de descarte (pilha pré-existente de entulho/"
        "restos ao longo da base do muro). Tráfego intenso PASSA pela via sem parar. Descartes "
        "reais: alguém (a pé, carroça/carrinho ou veículo) PARA junto ao muro à direita e deposita."),
}

ARRUDA_V2 = dg.SYSTEM_PROMPT + """

CONTEXTO DESTA CAMERA (ponto cronico - Arruda): a faixa DIREITA da via tem residuo
espalhado permanentemente; "pessoa perto do lixo" NAO e evidencia aqui.
REJEITE (infraction_confirmed=false) estes padroes recorrentes: catador revirando/
recolhendo itens da pilha SEM trazer material; animal mexendo no lixo; pessoa,
carrinho/carroca, bicicleta ou veiculo que para ou passa SEM deixar material novo;
trafego e pedestres em transito.
CONFIRME quando: material novo visivel no chao que nao estava no primeiro frame, OU o
agente e visto largando/derramando material que trouxe (mao/carrinho/cacamba -> chao),
OU agente estacionario manuseando material proprio junto a faixa e saindo sem ele.
Seja CONCISO: maximo 1 frase curta em cada campo de texto do JSON.
""".strip()

REPS = 2


def run(frames, arm):
    prev = dg.SYSTEM_PROMPT
    if arm == "arruda_v2":
        dg.SYSTEM_PROMPT = ARRUDA_V2
    try:
        r = dg.analyze_with_gemini(
            image_paths=frames, camera_context=ARRUDA_CTX,
            request_id=f"b38b-{arm}-{uuid.uuid4().hex[:4]}",
            mosaic_mode="off", prior_window_context=None, prompt_version="current")
        rep = r.report
        return {"ok": True, "confirm": bool(rep.infraction_confirmed),
                "ev": (getattr(rep, "evidence", None) or "")[:160]}
    except Exception as e:
        return {"ok": False, "confirm": None, "err": f"{type(e).__name__}: {e}"[:160]}
    finally:
        dg.SYSTEM_PROMPT = prev


def main():
    events = []
    for d in sorted(CORPUS.iterdir()):
        if not d.is_dir():
            continue
        det8 = d.name
        frames = [Path(f) for f in sorted(glob.glob(str(d / "*.jpg")))]
        if len(frames) < 5:
            continue
        st = STATUS.get(det8) or ("INDET" if det8 in INDET else ("REJ" if det8 in REJ_IDS else "?"))
        events.append((det8, st, frames))
    print(f"Campaign 38b — ARRUDA_V2 x{REPS} reps | {len(events)} eventos", flush=True)
    rows = []
    for det8, st, frames in events:
        rec = {"id": det8, "status": st, "runs": []}
        marks = []
        for rp in range(REPS):
            res = run(frames, "arruda_v2")
            rec["runs"].append(res)
            marks.append("C" if res.get("confirm") else ("E" if not res.get("ok") else "."))
            time.sleep(0.3)
        print(f"  {st:6}/{det8}({len(frames)}f) v2={''.join(marks)}", flush=True)
        rows.append(rec)

    print("\n=== SUMMARY (por rep) ===", flush=True)
    for rp in range(REPS):
        parts = []
        for coh in ("REJ", "CONF", "INDET", "COLETA"):
            rs = [r for r in rows if r["status"] == coh and r["runs"][rp].get("ok")]
            c = sum(1 for r in rs if r["runs"][rp]["confirm"])
            parts.append(f"{coh} {c}/{len(rs)}")
        print(f"  rep{rp}: " + " | ".join(parts), flush=True)
    errs = sum(1 for r in rows for rr in r["runs"] if not rr.get("ok"))
    print(f"  ERRs totais: {errs}", flush=True)
    (CAMP / "results_38b.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved results_38b.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
