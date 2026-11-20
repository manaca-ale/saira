#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — DeepSeek como GATE (missao 4b), nos mesmos conjuntos do run_gate54.py.

Por que existe: o Gabriel iniciou o DeepSeek como cascata no testspace (`detector_deepseek.py`, modelo
`deepseek-flash`, `thinking` desligado, JSON em texto com o esquema colado no system prompt). O Alexandre
pediu em 19/11/2026 para medir, variando parametros, se ele serve de gate quando o gemini-2.5-flash-lite
sair. Teto US$ 3,00 (carteira `deepseek` do budget.json).

Mesma medida dos bracos Gemini e Nova: os 5 frames que o gate de producao viu, o prompt do worker (system
e user), o esquema GeminiNewLitterReport e a pos-regra do worker (cena DUMPING + 2 de 3 sinais; dispara com
confianca >= 85). Registro no formato do run_gate54.py (`new_litter` e `conf` DEPOIS da pos-regra), entao
`agg_gate54.py` e `cmp_gate54_reps.py` leem sem mudanca; a resposta crua fica em `new_litter_raw`/`conf_raw`.

Bracos: dsf_<prompt>_<img>[_ctx] (thinking desligado, como no testspace) e dsft_<prompt>_<img>[_ctx]
(thinking ligado). Prompts v1, g3, v1p e `rcl` (o RECALL_GATE_PROMPT do testspace, copiado em prompts54.py;
aqui com o esquema e a pos-regra do worker, nao com o RecallGateReport dele); imagens `low`
(640 px, qualidade 70) ou `orig` (bytes do disco).
`_ctx` = com o aviso da janela anterior que a producao mandava (run_gate54.prior_contexts).

Custo: a trava cobra SEMPRE o preco de pico (0,30 / 1,20 por 1M); fora do pico (01h-03h e 07h-22h de
Brasilia em dias uteis, e fins de semana) o custo real e a metade e fica em `cost_usd_offpeak`.

Credencial: variavel DEEPSEEK_API_KEY de C:\\Saira-testspace\\.env, lida so pelo nome e nunca impressa.
O repo do testspace NAO e alterado (so lido).

So o conjunto de DESENVOLVIMENTO. Sempre --dry-run antes.

Uso:
  python run_gate54_deepseek.py --arm dsf_v1p_low_ctx --set tri --dry-run
  python run_gate54_deepseek.py --arm dsf_v1p_low_ctx --set tri --limit 2 --max-usd 0.02    # sonda de tokens
  python run_gate54_deepseek.py --arm dsf_v1p_low_ctx --set tri --max-usd 0.50
Saida: ../results/gate54__<braco>__r<rep>.jsonl (um registro por evento; retoma de onde parou).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_gate54_bedrock as rb           # noqa: E402  (prompts, pos-regra do V1 e os conjuntos)
from worker.schemas_gemini import GeminiNewLitterReport  # noqa: E402
from bench_budget import Budget, cost_usd  # noqa: E402

g = rb.g
b = g.b
dg = b.dg

ENV_FILE = Path(r"C:\Saira-testspace\.env")
TESTSPACE_CLIENT = Path(r"C:\Saira-testspace\services\yolo-worker-vm\src\worker\detector_deepseek.py")
API_URL_DEFAULT = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
WALLET = "deepseek"

# Estimativa por chamada (US$, preco de pico) para o --dry-run. `off`+`low` medido na sonda de 19/11 (2.541 tokens de entrada, ~270 de saida); o resto e chute.
EST = {("off", "low"): 0.0012, ("off", "orig"): 0.0040, ("on", "low"): 0.0040, ("on", "orig"): 0.0060}
PROMPT_NAMES = (*rb.PROMPTS, "rcl")
ARMS = {f"{'dsft' if th == 'on' else 'dsf'}_{pv}_{img}": {"prompt": pv, "img": img, "think": th, "est": EST[(th, img)]}
        for th in ("off", "on") for pv in PROMPT_NAMES for img in ("low", "orig")}
ARMS.update({k + "_ctx": {**v, "prior": "prod"} for k, v in list(ARMS.items())})


def read_key() -> str:
    """Le so a variavel DEEPSEEK_API_KEY, pelo nome. Nunca imprime."""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DEEPSEEK_API_KEY nao encontrada no .env do testspace")


def gate_prompt(name: str) -> str:
    """Prompts do worker pelo run_gate54_bedrock; `rcl` = copia do RECALL_GATE_PROMPT do testspace (prompts54.py)."""
    import prompts54
    return prompts54.GATE_PROMPTS[name] if name == "rcl" else rb.PROMPTS[name]


def fit_schema(text: str) -> tuple[str, list[str]]:
    """Corta os textos que passam do tamanho maximo do esquema (com thinking ligado, 57% das respostas
    estouravam os 500 caracteres e eram perdidas). Devolve o JSON ajustado e os campos cortados."""
    try:
        obj = json.loads(text)
    except ValueError:
        return text, []
    cut = []
    for k, sch in (GeminiNewLitterReport.model_json_schema().get("properties") or {}).items():
        lim = sch.get("maxLength")
        if lim and isinstance(obj.get(k), str) and len(obj[k]) > lim:
            obj[k] = obj[k][:lim]
            cut.append(k)
    return (json.dumps(obj, ensure_ascii=False), cut) if cut else (text, [])


def api_url() -> str:
    """Mesmo endereco que o cliente do testspace usa (lido do codigo dele, sem importar)."""
    try:
        m = re.search(r"_API_URL\s*=\s*[\"']([^\"']+)[\"']", TESTSPACE_CLIENT.read_text(encoding="utf-8"))
        return m.group(1) if m else API_URL_DEFAULT
    except OSError:
        return API_URL_DEFAULT


def system_with_schema(system_prompt: str) -> str:
    """Como o detector_deepseek.build_system_prompt do testspace: esquema e exemplo colados no system."""
    schema = GeminiNewLitterReport.model_json_schema()
    example = {k: {"boolean": False, "integer": 0, "number": 0, "string": "example", "array": [],
                   "object": {}}.get(s.get("type")) for k, s in (schema.get("properties") or {}).items()}
    return (system_prompt + "\nReturn one JSON object matching the JSON schema below. "
            "Use the schema, not the illustrative values, for the actual answer.\n"
            f"Example JSON object: {json.dumps(example, ensure_ascii=False)}\n"
            f"JSON schema: {json.dumps(schema, ensure_ascii=False)}")


def prepare(paths, mode: str) -> list[bytes]:
    blobs = []
    for p in paths:
        data = p.read_bytes()
        if mode == "low":
            from PIL import Image
            im = Image.open(io.BytesIO(data)).convert("RGB")
            if im.width > 640:
                im = im.resize((640, round(im.height * 640 / im.width)), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
            data = buf.getvalue()
        blobs.append(data)
    return blobs


def call(key: str, url: str, system: str, user: str, blobs: list[bytes], think: bool, max_tokens: int):
    content = [{"type": "text", "text": user}]
    content += [{"type": "image_url",
                 "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(x).decode("ascii")}} for x in blobs]
    body = {"model": MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "enabled" if think else "disabled"},
            "temperature": 0.0, "max_tokens": max_tokens}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = ""
    for attempt in range(3):
        req = Request(url, data=data, method="POST",
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        t0 = time.time()
        try:
            with urlopen(req, timeout=180) as resp:
                return json.load(resp), int((time.time() - t0) * 1000)
        except HTTPError as exc:
            # so o codigo e o comeco do corpo da resposta; nunca a requisicao nem a credencial
            last = f"HTTP {exc.code}: {exc.read()[:200].decode('utf-8', 'replace')}"
            if exc.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--set", default="tri", choices=["tri", "pass", "s0fail"])
    ap.add_argument("--subs", default="", help="so estes estratos, separados por virgula (ex.: S2C,S0)")
    ap.add_argument("--thr", type=float, default=0.30)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    spec = ARMS[a.arm]
    think = spec["think"] == "on"
    events = g.build_set(a.set, a.thr)
    if a.subs:
        keep = {s.strip() for s in a.subs.split(",") if s.strip()}
        events = [e for e in events if e["sub"] in keep]
    path = g.out_path(a.arm, a.rep)
    done = b.latest_ok(path) if path.exists() else {}
    todo = [e for e in events if e["event_id"] not in done]
    if a.limit:
        todo = todo[: a.limit]
    for e in todo:
        e["frames"] = [g.frame_path(n) for n in e["gate5"].split("|")]
    missing = [e["event_id"] for e in todo if len(e["frames"]) < 2 or any(f is None for f in e["frames"])]
    todo = [e for e in todo if e["event_id"] not in set(missing)]
    est = len(todo) * spec["est"]
    n_sub = {}
    for e in events:
        n_sub[e["sub"]] = n_sub.get(e["sub"], 0) + 1
    print(f"[gate54/deepseek] braco={a.arm} modelo={MODEL} prompt={spec['prompt']} imagens={spec['img']} "
          f"thinking={spec['think']}")
    print(f"  conjunto={a.set} (limiar {a.thr}) eventos={len(events)} {dict(sorted(n_sub.items()))} "
          f"ja_feitos={len(events) - len(todo) - len(missing)} a_rodar={len(todo)} sem_frames={len(missing)} "
          f"estimativa=US$ {est:.4f} (preco de pico)")
    if a.dry_run or not todo:
        return
    if a.max_usd <= 0:
        raise SystemExit("informe --max-usd")

    budget = Budget(wallet=WALLET)
    budget.run_cap = a.max_usd
    budget.require(est, f"gate54/{a.arm}")
    ctx = {"campaign": "54", "stage": "gate54", "arm": a.arm, "rep": a.rep,
           "dataset": "picam-historico", "backend": "deepseek"}
    key, url = read_key(), api_url()
    system = system_with_schema(gate_prompt(spec["prompt"]))
    prior = g.prior_contexts() if spec.get("prior") == "prod" else {}

    def one(ev):
        fr = ev["frames"]
        rec = {"stage": "gate54", "arm": a.arm, "rep": a.rep, "event_id": ev["event_id"],
               "estrato": ev["estrato"], "sub": ev["sub"], "split": ev["split"], "status": ev["status"],
               "detection_id": ev["detection_id"], "score": ev["score"], "model": MODEL, "model_id": MODEL,
               "prompt": spec["prompt"], "budget": None, "think": spec["think"], "media": spec["img"],
               "flex_requested": False, "n_sent": len(fr), "backend": "deepseek",
               "ts": dt.datetime.now().isoformat(timespec="seconds"), "error": ""}
        p_type, p_delta, p_src = prior.get(ev["event_id"], (None, None, "desligado"))
        rec.update({"prior_type": p_type, "prior_delta": p_delta, "prior_src": p_src})
        if budget.stop:
            rec["error"] = "budget_stop"
            return rec
        try:
            blobs = prepare(fr, spec["img"])
            user = dg._new_litter_user_prompt(
                first_frame_name=fr[0].name, last_frame_name=fr[-1].name, camera_context=b.camera_context(fr),
                prior_window_context=g.prior_text(p_type), mosaic=False, mid_frame_names=[p.name for p in fr[1:-1]])
            res, lat = call(key, url, system, user, blobs, think, 4000 if think else 2000)
            usage = res.get("usage") or {}
            tok_in = int(usage.get("prompt_tokens") or 0)
            tok_all = int(usage.get("completion_tokens") or 0)
            tok_think = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
            tok_out = max(0, tok_all - tok_think)
            if tok_in:
                budget.charge(MODEL, tok_in, tok_out, tok_think, ctx=ctx)
            peak = cost_usd(MODEL, tok_in, tok_out, tok_think, wallet=WALLET)
            rec.update({"tok_in": tok_in, "tok_out": tok_out, "tok_think": tok_think,
                        "cost_usd": round(peak, 8), "cost_usd_offpeak": round(peak / 2, 8), "latency_ms": lat,
                        "payload_kb": round(sum(len(x) for x in blobs) / 1024, 1),
                        "model_returned": res.get("model"),
                        "cache_hit_tokens": usage.get("prompt_cache_hit_tokens")})
            choices = res.get("choices") or []
            text = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            text, cut = fit_schema(text)
            rec["cut_fields"] = cut
            try:
                rep = GeminiNewLitterReport.model_validate_json(text)
            except Exception as exc:  # noqa: BLE001
                rec["error"] = f"json invalido: {type(exc).__name__}: {str(exc)[:160]}"
                rec["raw"] = text[:1500]
                return rec
            rep.confidence_0_100 = max(0, min(100, int(rep.confidence_0_100)))
            v1 = rb.apply_v1_gate(rep)
            conf = int(v1.confidence_0_100)
            rec.update({
                "new_litter": bool(v1.new_litter_detected), "conf": conf,
                "fire": int(bool(v1.new_litter_detected) and conf >= b.TRIGGER_THR),
                "new_litter_raw": bool(rep.new_litter_detected), "conf_raw": int(rep.confidence_0_100),
                "scene_type": (getattr(rep, "scene_type", "") or "").upper().strip(),
                "veh_stopped": bool(getattr(rep, "vehicle_stopped", False)),
                "person_handling": bool(getattr(rep, "person_handling_material", False)),
                "new_ground": bool(getattr(rep, "new_ground_material", False)),
                "evidence": (getattr(rep, "evidence_summary", "") or "")[:300]})
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        return rec

    n_ok = n_err = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for i, fut in enumerate(as_completed([pool.submit(one, ev) for ev in todo]), 1):
            r = fut.result()
            b.append_jsonl(path, r)
            if r["error"]:
                n_err += 1
                print(f"  [{i}/{len(todo)}] {r['sub']} {r['event_id']} ERR {r['error'][:200]}", flush=True)
            else:
                n_ok += 1
                if i <= 2 or i % 50 == 0 or i == len(todo):
                    print(f"  [{i}/{len(todo)}] ok={n_ok} erros={n_err} tok_in={r['tok_in']} tok_out={r['tok_out']} "
                          f"tok_think={r['tok_think']} US$/chamada={r['cost_usd']:.6f} lat={r['latency_ms']} ms "
                          f"fire={r['fire']} | gasto=US$ {budget.run_spent:.4f} ({int(time.time() - t0)} s)", flush=True)
    print(f"  fim: ok={n_ok} erros={n_err} gasto_desta_execucao=US$ {budget.run_spent:.4f} "
          f"total_carteira_deepseek=US$ {budget.spent:.4f} ({int(time.time() - t0)} s)")


if __name__ == "__main__":
    main()
