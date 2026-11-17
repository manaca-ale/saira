#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Teto de gasto compartilhado para benchmarks pagos.

Um ledger JSONL (fora do repo, para sobreviver a troca de branch) recebe uma linha por
chamada de API, com tokens e custo a PRECO DE LISTA. O teto vem de um arquivo de
configuracao ao lado do ledger. Runners chamam:

    budget = Budget()                    # le ~/.saira-bench/budget.json
    budget.require(estimativa, "o que")  # antes de comecar um braco
    budget.charge(model=..., tok_in=..., tok_out=..., tok_think=..., ctx={...})
    if budget.stop: ...                  # parar de submeter chamadas novas

`charge` nunca levanta excecao (o chamador pode estar dentro de um loop de retry do
worker, e uma excecao ali causaria NOVAS chamadas pagas). Ele liga `budget.stop`.

Arquivos (padrao em ~/.saira-bench, trocavel por BENCH_BUDGET_DIR):
    budget.json        {"cap_usd": 15.0, "since": "2026-11-16", "note": "..."}
    api_ledger.jsonl   uma linha por chamada

Uso direto:  python bench_budget.py            -> mostra gasto e saldo
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path

# USD por 1M tokens: (entrada, saida). Thinking e cobrado como saida.
# Tabela Standard conferida em 2026-11-16 em aistudio.google.com/docs/pricing.
# O Vertex (global) bateu com esta tabela no 3.1-flash-lite em 2026-11-13 (catalogo
# de SKUs); para os demais modelos a igualdade Vertex == Developer API e SUPOSICAO.
PRICES = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-4-hydrogen": (1.50, 7.50),
    "gemini-decision-1": (0.10, 0.0),
}
# Precos anunciados a partir de 2027-01-01 (so os que mudam).
PRICES_2027 = {
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.8-flash": (1.50, 7.50),
}
# Faturamento separado: o teto vale para a conta "Saira - Testes" (Vertex). A API de
# Decisoes roda numa chave do AI Studio de outro projeto, com creditos proprios (informado
# pelo Alexandre em 2026-11-17: "chave separada, com creditos separados"). Esses registros
# ficam no ledger e aparecem no resumo, mas NAO contam no teto.
SEPARATE_BILLING_MODELS = {"gemini-decision-1"}
SEPARATE_BILLING_ARMS = {"sondas_chave_aistudio"}


def is_separate(rec: dict) -> bool:
    return (str(rec.get("model", "")).lower() in SEPARATE_BILLING_MODELS
            or str(rec.get("arm", "")) in SEPARATE_BILLING_ARMS)


# Margem: para de submeter chamadas novas quando faltar menos que isto para o teto
# (chamadas em voo ainda terminam e sao cobradas).
SAFETY_MARGIN_USD = 0.25


class BudgetExceeded(RuntimeError):
    pass


def price(model: str, year2027: bool = False) -> tuple[float, float]:
    m = (model or "").strip().lower()
    if year2027 and m in PRICES_2027:
        return PRICES_2027[m]
    if m not in PRICES:
        raise KeyError(f"modelo sem preco em bench_budget.PRICES: {model!r}")
    return PRICES[m]


def cost_usd(model: str, tok_in: int, tok_out: int, tok_think: int = 0,
             year2027: bool = False) -> float:
    pin, pout = price(model, year2027)
    return tok_in / 1e6 * pin + (tok_out + tok_think) / 1e6 * pout


def budget_dir() -> Path:
    return Path(os.environ.get("BENCH_BUDGET_DIR", str(Path.home() / ".saira-bench")))


class Budget:
    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory) if directory else budget_dir()
        self.cfg_path = self.dir / "budget.json"
        self.ledger_path = self.dir / "api_ledger.jsonl"
        if not self.cfg_path.exists():
            raise BudgetExceeded(
                f"sem orcamento aprovado: {self.cfg_path} nao existe. "
                "Chamadas pagas so rodam com teto definido.")
        cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        self.cap = float(cfg["cap_usd"])
        self.since = str(cfg.get("since", "1970-01-01"))
        self._lock = threading.Lock()
        self._spent = self._read_spent()
        self.stop = self._spent >= self.cap - SAFETY_MARGIN_USD
        self.run_cap: float | None = None      # teto opcional desta execucao
        self._run_spent = 0.0

    def _read_spent(self) -> float:
        total = 0.0
        if self.ledger_path.exists():
            with self.ledger_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(rec.get("ts", ""))[:10] >= self.since and not is_separate(rec):
                        total += float(rec.get("cost_usd") or 0.0)
        return total

    @property
    def spent(self) -> float:
        return self._spent

    @property
    def remaining(self) -> float:
        return self.cap - self._spent

    @property
    def run_spent(self) -> float:
        return self._run_spent

    def require(self, estimate_usd: float, what: str) -> None:
        """Recusa comecar algo cuja estimativa nao cabe no saldo."""
        room = self.remaining - SAFETY_MARGIN_USD
        if estimate_usd > room:
            raise BudgetExceeded(
                f"{what}: estimativa US$ {estimate_usd:.2f} > saldo util US$ {room:.2f} "
                f"(teto {self.cap:.2f}, gasto {self._spent:.2f})")
        if self.run_cap is not None and estimate_usd > self.run_cap - self._run_spent:
            raise BudgetExceeded(
                f"{what}: estimativa US$ {estimate_usd:.2f} > teto desta execucao "
                f"US$ {self.run_cap:.2f} (ja gasto {self._run_spent:.2f})")

    def charge(self, model: str, tok_in: int, tok_out: int, tok_think: int = 0,
               ctx: dict | None = None, discount: float = 1.0) -> float:
        """`discount` = fracao do preco de lista realmente cobrada (0.5 no Flex PayGo).
        `cost_usd` no ledger e o valor COBRADO; `list_usd` e o preco de lista."""
        try:
            full = cost_usd(model, tok_in, tok_out, tok_think)
        except KeyError:
            # modelo desconhecido: cobra pelo preco mais caro da tabela, para errar a favor do teto
            pin = max(p[0] for p in PRICES.values())
            pout = max(p[1] for p in PRICES.values())
            full = tok_in / 1e6 * pin + (tok_out + tok_think) / 1e6 * pout
        c = full * discount
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "model": model,
               "tok_in": int(tok_in), "tok_out": int(tok_out), "tok_think": int(tok_think),
               "cost_usd": round(c, 8), "list_usd": round(full, 8)}
        if ctx:
            rec.update({k: v for k, v in ctx.items() if k not in rec})
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._run_spent += c
            if not is_separate(rec):
                self._spent += c
            if self._spent >= self.cap - SAFETY_MARGIN_USD:
                self.stop = True
            if self.run_cap is not None and self._run_spent >= self.run_cap:
                self.stop = True
        return c

    def summary(self) -> dict:
        by: dict[str, float] = {}
        n = 0
        separate = 0.0
        if self.ledger_path.exists():
            with self.ledger_path.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(rec.get("ts", ""))[:10] < self.since:
                        continue
                    n += 1
                    if is_separate(rec):
                        separate += float(rec.get("cost_usd") or 0.0)
                    key = f"{rec.get('campaign', '?')}/{rec.get('stage', '?')}/{rec.get('arm', '?')}"
                    by[key] = by.get(key, 0.0) + float(rec.get("cost_usd") or 0.0)
        return {"cap_usd": self.cap, "spent_usd": round(self._spent, 4),
                "remaining_usd": round(self.remaining, 4),
                "separate_billing_usd": round(separate, 4),   # AI Studio, fora do teto
                "calls": n, "since": self.since,
                "by_arm": {k: round(v, 4) for k, v in sorted(by.items())}}


if __name__ == "__main__":
    print(json.dumps(Budget().summary(), ensure_ascii=False, indent=2))
