# -*- coding: utf-8 -*-
"""Gate de cada modelo ja testado, separado por conjunto de rotulos.

Camp 48 usa os rotulos ANTIGOS (30 tp / 37 fp / 40 baseline).
Camp 49 usa os rotulos REVISADOS pela Fase 0 (35 tp / 32 fp / 40 baseline).
Comparar entre camps sem separar seria erro.
"""
import csv, glob, collections

FONTES = [
    ("Camp 48 — rotulos antigos", r"c:\saira\benchmarks\campaigns\48-*\results\bench_bedrock.csv"),
    ("Camp 48 — screen (n=18)", r"c:\saira\benchmarks\campaigns\48-*\results\bench_bedrock_screen.csv"),
    ("Camp 49 — rotulos revisados", r"c:\saira\benchmarks\campaigns\49-*\results\bench_v4.csv"),
    ("Camp 49 — controle Gemini", r"c:\saira\benchmarks\campaigns\49-*\results\bench_v4_gemini.csv"),
]

# preco por 1M (in, out) — para custo do gate com 5 quadros
PRECO = {"kimi-k2.5": (0.60, 3.00), "magistral-small": (0.50, 1.50),
         "qwen3-vl-235b": (0.53, 2.66), "gemma-3-12b": (0.09, 0.29),
         "gemma-3-27b": (0.23, 0.38), "ministral-3-14b": (0.20, 0.20),
         "palmyra-vision-7b": (0.15, 0.60)}
TOK_IN, TOK_OUT = 3275, 200          # gate de 5 quadros a 640px + prompt


def custo_gate(alias):
    p = PRECO.get(alias)
    return TOK_IN / 1e6 * p[0] + TOK_OUT / 1e6 * p[1] if p else None


for titulo, pat in FONTES:
    rows = []
    for p in glob.glob(pat):
        rows += list(csv.DictReader(open(p, encoding="utf-8")))
    if not rows:
        continue
    agg = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    err = collections.Counter()
    for r in rows:
        arm = r["arm"]
        if "casc" not in arm and not arm.startswith("current"):
            continue
        if r.get("error"):
            err[arm] += 1
            continue
        try:
            fire = int(float(r.get("gate_fire") or 0))
        except ValueError:
            continue
        cat = (r.get("category") or "?").strip().lower()
        agg[arm][cat][0] += fire
        agg[arm][cat][1] += 1
        agg[arm]["TOT"][0] += fire
        agg[arm]["TOT"][1] += 1

    print(f"\n### {titulo}")
    print(f"{'braço':<30}{'passa TP':>13}{'passa FP':>13}{'passa BASE':>13}"
          f"{'passa tudo':>13}{'US$/gate':>11}{'err':>5}")
    print("-" * 98)

    def rec(a):
        return a["tp"][0] / a["tp"][1] if a["tp"][1] else -1
    for arm in sorted(agg, key=lambda a: -rec(agg[a])):
        d = agg[arm]
        if d["TOT"][1] < 15:
            continue
        alias = arm.split(":")[0]
        cg = custo_gate(alias)
        cgs = f"{cg:.5f}" if cg else ("0.00100" if arm.startswith("current") else "—")
        def c(k):
            a = d[k]
            return f"{a[0]}/{a[1]} ({100*a[0]/a[1]:.0f}%)" if a[1] else "—"
        marca = "  <<< controle" if arm.startswith("current") else ""
        print(f"{arm:<30}{c('tp'):>13}{c('fp'):>13}{c('baseline'):>13}"
              f"{c('TOT'):>13}{cgs:>11}{err.get(arm,0):>5}{marca}")

print("\nUS$/gate = 5 quadros a 640px (3.275 tok in / 200 out). Gate Gemini de prod = 0,00100 medido.")
