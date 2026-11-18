#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Teto de gasto compartilhado para benchmarks pagos.

Um ledger JSONL (fora do repo, para sobreviver a troca de branch) recebe uma linha por
chamada de API, com tokens e custo estimado (tokens x preco). O teto vem de um arquivo de
configuracao ao lado do ledger. Runners chamam:

    budget = Budget()                    # carteira "vertex" (padrao)
    budget = Budget(wallet="aistudio")   # chave do AI Studio, creditos e teto proprios
    budget.require(estimativa, "o que")  # antes de comecar um braco
    budget.charge(model=..., tok_in=..., tok_out=..., tok_think=..., ctx={...})
    if budget.stop: ...                  # parar de submeter chamadas novas

`charge` nunca levanta excecao (o chamador pode estar dentro de um loop de retry do
worker, e uma excecao ali causaria NOVAS chamadas pagas). Ele liga `budget.stop`.

Duas carteiras, porque sao dois faturamentos:
    vertex    conta "Saira - Testes" (Vertex AI). R$ 100 aprovados em 2026-11-16.
    aistudio  chave do AI Studio de outro projeto, com creditos proprios. Usada pela API de
              Decisoes desde 2026-11-16; em 2026-11-17 o Alexandre autorizou mais R$ 100
              nela para terminar os testes se o teto do Vertex acabar.

Arquivos (padrao em ~/.saira-bench, trocavel por BENCH_BUDGET_DIR):
    budget.json        {"cap_usd": 15.0, "since": "...", "wallets": {"vertex": {...}, "aistudio": {...}}}
    api_ledger.jsonl   uma linha por chamada

O valor e ESTIMATIVA. Para conferir: `python vertex_usage_check.py` (tokens contra a medicao
do Google) e `python vertex_sku_prices.py` (precos no catalogo de cobranca).

Uso direto:  python bench_budget.py            -> mostra gasto e saldo das duas carteiras
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path

# USD por 1M tokens: (entrada, saida). Thinking e cobrado como saida.
# Precos do VERTEX (endpoint global, chamada sincrona), que e onde os benchmarks e a
# producao rodam. Conferidos em 2026-11-17 no catalogo de cobranca do Google Cloud
# (`python vertex_sku_prices.py`) para 2.5-flash, 2.5-flash-lite, 3.5-flash-lite e
# 3.8-flash; o 3.1-flash-lite foi conferido em 2026-11-13. Flex PayGo = metade, tambem
# conferido no catalogo.
# ATENCAO: a pagina de precos da API do AI Studio lista o 3.6/3.8-flash a 0,75 / 3,75
# "ate 31/12/2026". No Vertex o catalogo ja cobra 1,50 / 7,50. Esta tabela usou o preco
# do AI Studio ate 2026-11-17 e subestimou pela metade todo gasto com o 3.8-flash; o
# ledger recebeu um registro de ajuste. O 3.6-flash NAO foi conferido no catalogo (a API
# respondeu 429): assumido igual ao 3.8-flash, como na pagina do AI Studio. O
# gemini-4-hydrogen e o gemini-3-flash-preview vem da pagina do AI Studio, sem conferencia.
PRICES = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.8-flash": (1.50, 7.50),
    "gemini-4-hydrogen": (1.50, 7.50),
    "gemini-decision-1": (0.10, 0.0),
}
# Onde a API do AI Studio cobra diferente do Vertex (pagina aistudio.google.com/docs/pricing,
# lida em 2026-11-16; NAO conferido em fatura). Vale ate 2026-12-31; depois, 1,50 / 7,50.
PRICES_AISTUDIO = {
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
}
# Mudancas de preco anunciadas para 2027-01-01. No Vertex nao ha nenhuma conhecida: o
# 3.8-flash ja esta no valor que a pagina do AI Studio anuncia para 2027.
PRICES_2027: dict = {}

WALLETS = ("vertex", "aistudio")
# Registros antigos nao tem o campo `wallet`: estes eram os que rodavam na chave do AI Studio.
SEPARATE_BILLING_MODELS = {"gemini-decision-1"}
SEPARATE_BILLING_ARMS = {"sondas_chave_aistudio"}


def is_separate(rec: dict) -> bool:
    """True para registros da carteira do AI Studio (compatibilidade com registros antigos)."""
    return wallet_of(rec) == "aistudio"


def wallet_of(rec: dict) -> str:
    w = rec.get("wallet")
    if w in WALLETS:
        return w
    if (str(rec.get("model", "")).lower() in SEPARATE_BILLING_MODELS
            or str(rec.get("arm", "")) in SEPARATE_BILLING_ARMS):
        return "aistudio"
    return "vertex"


# Margem: para de submeter chamadas novas quando faltar menos que isto para o teto
# (chamadas em voo ainda terminam e sao cobradas).
SAFETY_MARGIN_USD = 0.25


class BudgetExceeded(RuntimeError):
    pass


def price(model: str, year2027: bool = False, wallet: str = "vertex") -> tuple[float, float]:
    m = (model or "").strip().lower()
    if year2027 and m in PRICES_2027:
        return PRICES_2027[m]
    if wallet == "aistudio" and m in PRICES_AISTUDIO:
        return PRICES_AISTUDIO[m]
    if m not in PRICES:
        raise KeyError(f"modelo sem preco em bench_budget.PRICES: {model!r}")
    return PRICES[m]


def cost_usd(model: str, tok_in: int, tok_out: int, tok_think: int = 0,
             year2027: bool = False, wallet: str = "vertex") -> float:
    """Custo estimado. O padrao (`wallet="vertex"`) e o preco de PRODUCAO, que roda no
    Vertex: use-o para custo por evento. `wallet="aistudio"` e o que a chave do AI Studio
    cobra pelo mesmo teste."""
    pin, pout = price(model, year2027, wallet)
    return tok_in / 1e6 * pin + (tok_out + tok_think) / 1e6 * pout


def budget_dir() -> Path:
    return Path(os.environ.get("BENCH_BUDGET_DIR", str(Path.home() / ".saira-bench")))


def _cap_for(cfg: dict, wallet: str) -> float:
    w = (cfg.get("wallets") or {}).get(wallet)
    if isinstance(w, dict) and "cap_usd" in w:
        return float(w["cap_usd"])
    if wallet == "vertex" and "cap_usd" in cfg:
        return float(cfg["cap_usd"])
    raise BudgetExceeded(f"carteira '{wallet}' sem teto em budget.json: chamadas pagas nao rodam.")


class Budget:
    def __init__(self, directory: Path | None = None, wallet: str = "vertex"):
        if wallet not in WALLETS:
            raise ValueError(f"carteira desconhecida: {wallet!r} (use {WALLETS})")
        self.wallet = wallet
        self.dir = Path(directory) if directory else budget_dir()
        self.cfg_path = self.dir / "budget.json"
        self.ledger_path = self.dir / "api_ledger.jsonl"
        if not self.cfg_path.exists():
            raise BudgetExceeded(
                f"sem orcamento aprovado: {self.cfg_path} nao existe. "
                "Chamadas pagas so rodam com teto definido.")
        self.cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        self.cap = _cap_for(self.cfg, wallet)
        self.since = str(self.cfg.get("since", "1970-01-01"))
        self._lock = threading.Lock()
        self._spent = self._read_spent().get(wallet, 0.0)
        self.stop = self._spent >= self.cap - SAFETY_MARGIN_USD
        self.run_cap: float | None = None      # teto opcional desta execucao
        self._run_spent = 0.0

    def _records(self):
        if not self.ledger_path.exists():
            return
        with self.ledger_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(rec.get("ts", ""))[:10] >= self.since:
                    yield rec

    def _read_spent(self) -> dict:
        total = {w: 0.0 for w in WALLETS}
        for rec in self._records() or ():
            total[wallet_of(rec)] += float(rec.get("cost_usd") or 0.0)
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
                f"{what}: estimativa US$ {estimate_usd:.2f} > saldo util US$ {room:.2f} da carteira "
                f"{self.wallet} (teto {self.cap:.2f}, gasto {self._spent:.2f})")
        if self.run_cap is not None and estimate_usd > self.run_cap - self._run_spent:
            raise BudgetExceeded(
                f"{what}: estimativa US$ {estimate_usd:.2f} > teto desta execucao "
                f"US$ {self.run_cap:.2f} (ja gasto {self._run_spent:.2f})")

    def charge(self, model: str, tok_in: int, tok_out: int, tok_think: int = 0,
               ctx: dict | None = None, discount: float = 1.0) -> float:
        """`discount` = fracao do preco realmente cobrada (0.5 no Flex PayGo).
        `cost_usd` no ledger e o valor COBRADO estimado nesta carteira; `list_usd`, o preco
        sem desconto na mesma carteira."""
        try:
            full = cost_usd(model, tok_in, tok_out, tok_think, wallet=self.wallet)
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
        rec["wallet"] = self.wallet
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._run_spent += c
            self._spent += c
            if self._spent >= self.cap - SAFETY_MARGIN_USD:
                self.stop = True
            if self.run_cap is not None and self._run_spent >= self.run_cap:
                self.stop = True
        return c

    def summary(self) -> dict:
        by: dict[str, float] = {}
        n = 0
        spent = {w: 0.0 for w in WALLETS}
        for rec in self._records() or ():
            n += 1
            w = wallet_of(rec)
            c = float(rec.get("cost_usd") or 0.0)
            spent[w] += c
            key = f"{w}:{rec.get('campaign', '?')}/{rec.get('stage', '?')}/{rec.get('arm', '?')}"
            by[key] = by.get(key, 0.0) + c
        wallets = {}
        for w in WALLETS:
            try:
                cap = _cap_for(self.cfg, w)
            except BudgetExceeded:
                cap = None
            wallets[w] = {"cap_usd": cap, "spent_usd": round(spent[w], 4),
                          "remaining_usd": round(cap - spent[w], 4) if cap is not None else None}
        return {"wallet": self.wallet, "cap_usd": self.cap, "spent_usd": round(self._spent, 4),
                "remaining_usd": round(self.remaining, 4),
                "separate_billing_usd": round(spent["aistudio"], 4),
                "wallets": wallets, "calls": n, "since": self.since,
                "by_arm": {k: round(v, 4) for k, v in sorted(by.items())}}


if __name__ == "__main__":
    s = Budget().summary()
    print(json.dumps({k: s[k] for k in ("wallets", "calls", "since")}, ensure_ascii=False, indent=2))
    print("ESTIMATIVA: tokens x preco. Conferir com vertex_usage_check.py e vertex_sku_prices.py.")
