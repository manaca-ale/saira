#!/usr/bin/env python3
"""Campaign 38 — Arruda (cam_14) detail prompt A/B to cut REVIEWREJ FPs.

Corpus: 59 prod detections with FULL exact windows (tmp/arruda_detail_corpus/<det8>/),
labels from DB review: 37 REJEITADO (detail false-confirms -> want REJECT),
10 CONFIRMADO (want CONFIRM), 11 INDETERMINADO + 1 COLETA (tracked).

Arms share the exact prod code path (analyze_with_gemini, prompt_version="current",
mosaic off, full window frames, gemini-2.5-flash); only SYSTEM_PROMPT is swapped:
- v1     : prod SYSTEM_PROMPT
- arruda : V1 + Arruda negative-first anti-patterns (spreadsheet FP taxonomy)
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
}  # everything else in det_frames_rej = REJ; remaining pos = INDET
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

ARRUDA_DETAIL = dg.SYSTEM_PROMPT + """

CONTEXTO ESPECIFICO DESTA CAMERA (ponto cronico - Arruda):
A faixa a DIREITA da via tem residuo espalhado em TODA a sua extensao, o tempo todo.
"Pessoa perto do lixo" NAO e evidencia aqui. Os 4 falsos positivos mais comuns desta
camera, que voce DEVE rejeitar (infraction_confirmed=false) na ausencia de prova positiva:
- AP1 CATADOR: pessoa que REVIRA/remexe/recolhe itens da pilha existente sem trazer
  material novo (inclui curvar-se, agachar, manusear residuo da pilha).
- AP2 ANIMAL: cachorro/animal mexendo no lixo.
- AP3 APROXIMACAO SEM LARGADA: pessoa, bicicleta, carrinho/carroca ou veiculo que para
  ou passa perto da faixa mas sai SEM deixar material novo visivel no chao.
- AP4 TRAFEGO: veiculos/pedestres passando ou estacionados.

PROVA POSITIVA (exigida para confirmar; pelo menos UMA, citada em evidence):
P1) Material novo VISIVEL no chao que NAO estava no primeiro frame — compare
    diretamente o primeiro e o ultimo frame da faixa direita.
P2) O agente e visto LARGANDO/DERRAMANDO material (objeto saindo das maos/carrinho/
    cacamba em direcao ao chao), nao apenas proximo da pilha.
Se nenhuma prova positiva for visivel, infraction_confirmed=false mesmo que haja pessoa
parada junto a pilha. NAO infira descarte a partir de presenca ou postura apenas.
""".strip()


def run(frames, arm):
    prev = dg.SYSTEM_PROMPT
    if arm == "arruda":
        dg.SYSTEM_PROMPT = ARRUDA_DETAIL
    try:
        r = dg.analyze_with_gemini(
            image_paths=frames, camera_context=ARRUDA_CTX,
            request_id=f"b38-{arm}-{uuid.uuid4().hex[:4]}",
            mosaic_mode="off", prior_window_context=None, prompt_version="current")
        rep = r.report
        return {"ok": True, "confirm": bool(rep.infraction_confirmed),
                "waste": getattr(rep, "waste_type", None),
                "ev": (getattr(rep, "evidence", None) or getattr(rep, "evidence_summary", "") or "")[:200]}
    except Exception as e:
        return {"ok": False, "confirm": None, "err": f"{type(e).__name__}: {e}"[:200]}
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
    print(f"Campaign 38 — detail V1 vs ARRUDA | {len(events)} eventos "
          f"(REJ={sum(1 for _,s,_ in events if s=='REJ')}, CONF={sum(1 for _,s,_ in events if s=='CONF')}, "
          f"INDET={sum(1 for _,s,_ in events if s=='INDET')})", flush=True)
    rows = []
    for det8, st, frames in events:
        rec = {"id": det8, "status": st, "n_frames": len(frames), "g": {}}
        line = [f"{st:6}/{det8}({len(frames)}f)"]
        for arm in ("v1", "arruda"):
            res = run(frames, arm)
            rec["g"][arm] = res
            mark = "CONFIRM" if res.get("confirm") else ("rej" if res.get("ok") else "ERR")
            line.append(f"{arm}={mark}")
            time.sleep(0.3)
        print("  " + " | ".join(line), flush=True)
        rows.append(rec)

    print("\n=== SUMMARY (confirm rate por cohort) ===", flush=True)
    for arm in ("v1", "arruda"):
        parts = []
        for coh in ("REJ", "CONF", "INDET", "COLETA"):
            rs = [r for r in rows if r["status"] == coh and r["g"][arm].get("ok")]
            c = sum(1 for r in rs if r["g"][arm]["confirm"])
            parts.append(f"{coh} {c}/{len(rs)}")
        print(f"  {arm:7}: " + " | ".join(parts), flush=True)
    (CAMP / "results_38.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved results_38.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
