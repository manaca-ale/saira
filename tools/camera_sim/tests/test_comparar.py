"""comparar.py: liga o que o teste fez ao previsto pelos nomes dos quadros (sem rede)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comparar as cp  # noqa: E402

PREV = [
    {"event_id": "evt-a", "sub": "S2C", "filtro_nota": "0.7000", "filtro_passa": "1",
     "gate_r1": "1", "gate_r2": "1", "detail_cru": "1", "previsto_alerta": "1"},
    {"event_id": "evt-b", "sub": "S0", "filtro_nota": "0.1000", "filtro_passa": "0",
     "gate_r1": "", "gate_r2": "", "detail_cru": "", "previsto_alerta": "0"},
]
ENVIOS = [{"event_id": "evt-a", "sim_event_id": "sim0-evt-a", "seco": False},
          {"event_id": "evt-b", "sim_event_id": "sim0-evt-b", "seco": False}]
MAN = {"sim0-evt-a": {"frames": ["pi-cam-sim-001/2026/11/25/a1.jpg", "pi-cam-sim-001/2026/11/25/a2.jpg"]},
       "sim0-evt-b": {"frames": ["pi-cam-sim-001/2026/11/25/b1.jpg", "pi-cam-sim-001/2026/11/25/b2.jpg"]}}
PF = [{"frames": ["a1.jpg", "a2.jpg"], "wl_v2": 0.66, "below_threshold": False, "request_id": "pf-a",
       "latency_ms": 2100, "error": ""},
      {"frames": ["b1.jpg", "b2.jpg"], "wl_v2": 0.12, "below_threshold": True, "request_id": "pf-b",
       "latency_ms": 1900, "error": ""}]
CAS = [{"window_first_frame": "a1.jpg", "window_last_frame": "a2.jpg", "agent1_triggered": True,
        "agent1_confidence": 90, "agent1_request_id": "g-a", "agent2_ran": True,
        "agent2_disposal": True, "agent2_request_id": "d-a"}]
CALLS = [
    {"request_id": "pf-a", "agent": "prefilter", "model": "gemini-decision-1", "success": "t",
     "estimated_cost_usd": "0.000169", "latency_ms": "2100"},
    {"request_id": "pf-b", "agent": "prefilter", "model": "gemini-decision-1", "success": "t",
     "estimated_cost_usd": "0.000169", "latency_ms": "1900"},
    {"request_id": "g-a", "agent": "gate", "model": "amazon.nova-lite-v1:0", "success": "f",
     "estimated_cost_usd": "0", "latency_ms": ""},
    {"request_id": "g-a", "agent": "gate", "model": "gemini-2.5-flash-lite", "success": "t",
     "estimated_cost_usd": "0.0007", "latency_ms": "3000"},
    {"request_id": "d-a", "agent": "detail", "model": "gemini-3.8-flash", "success": "t",
     "estimated_cost_usd": "0.019", "latency_ms": "20000"},
]


def test_join_follows_each_event_through_the_funnel():
    rows = {r["event_id"]: r for r in cp.join(PREV, ENVIOS, MAN, CAS, PF, CALLS)}
    a, b = rows["evt-a"], rows["evt-b"]
    assert (a["teste_filtro_passa"], a["teste_gate"], a["teste_detail"], a["teste_alerta"]) == (1, 1, 1, 1)
    assert a["teste_gate_reserva"] == 1 and a["teste_gate_modelo"] == "gemini-2.5-flash-lite"
    assert a["erros"] == 1 and abs(a["custo_usd"] - 0.019869) < 1e-9
    assert (b["teste_filtro_passa"], b["teste_gate"], b["teste_alerta"]) == (0, "", 0)
    text = cp.summary(list(rows.values()))
    assert "Filtro (passa): concorda em 2 de 2" in text and "Alerta: concorda em 2 de 2" in text
    assert "Quedas para a reserva Gemini no gate: 1" in text
