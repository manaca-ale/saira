"""Testes do reconciliador de config da câmera (cam_config.py).

Cobrem o que dá para validar sem a câmera: comparação tolerante, IP, dia/noite,
mapa desejado (obturador sempre; iluminador opt-in), o cálculo de drift com
ExposureValue2 write-only, o GATE de estabilidade e o fluxo reconcile com câmera
fake (idempotência, verify ancorado no GainMax, backoff, abort)."""
import json

import cam_config as cc


PROFILE = {
    "shutter": {
        "day": {"exposure_value2": 4, "gain_max": 70},
        "night": {"exposure_value2": 33.33, "gain_max": 50},
    },
    "day_start": "06:00",
    "night_start": "17:30",
    "lighting_enabled": False,
    "lighting": {"night_ir_light": 40, "night_whitelight_light": 0},
}

K_EV = "VideoInOptions[0].ExposureValue2"
K_GAIN = "VideoInOptions[0].GainMax"
K_IR_MODE = "Lighting_V2[0][1][0].Mode"
K_IR_LIGHT = "Lighting_V2[0][1][0].MiddleLight[0].Light"


def noop_sleep(_s):
    pass


# ---------------------------------------------------------------- puras
def test_num_eq_tolerant():
    assert cc._num_eq("33.33", "33.330000") is True
    assert cc._num_eq("70", "70") is True
    assert cc._num_eq("4", "33.33") is False
    assert cc._num_eq("Auto", "Auto") is True
    assert cc._num_eq("Auto", "Manual") is False


def test_camera_ip():
    assert cc.camera_ip({"IP_CAM_URL": "http://192.168.0.130/cgi-bin/x"}) == "192.168.0.130"
    assert cc.camera_ip({"RTSP_URL": "rtsp://a:b@10.0.0.9:554/x"}) == "10.0.0.9"
    assert cc.camera_ip({"FOO": "bar"}) is None


def test_current_mode():
    assert cc.current_mode(PROFILE, "12:00") == "day"
    assert cc.current_mode(PROFILE, "06:00") == "day"
    assert cc.current_mode(PROFILE, "17:30") == "night"
    assert cc.current_mode(PROFILE, "03:00") == "night"


def test_desired_shutter_only_when_lighting_off():
    d = cc.desired_keys(PROFILE, "day")
    assert d[K_EV] == "4" and d[K_GAIN] == "70"
    assert not any(k.startswith("Lighting_V2") for k in d)   # opt-in desligado


def test_desired_night_shutter():
    d = cc.desired_keys(PROFILE, "night")
    assert d[K_EV] == "33.33" and d[K_GAIN] == "50"


def test_desired_lighting_opt_in_command():
    prof = dict(PROFILE, lighting_enabled=True)
    d = cc.desired_keys(prof, "night")
    # comando CORRETO: Mode + MiddleLight (não PercentOfMaxBrightness), perfil noite
    assert d[K_IR_MODE] == "Manual" and d[K_IR_LIGHT] == "40"
    assert d["Lighting_V2[0][1][1].NearLight[0].Light"] == "0"


def test_exposure_no_verify_does_not_drift():
    # ExposureValue2 lê diferente (auto-varia) mas NÃO dispara drift sozinho
    assert cc.compute_drift({K_EV: "4", K_GAIN: "70"},
                            {K_EV: "17.5", K_GAIN: "70"}) == {}


def test_gainmax_drift_detected():
    assert cc.compute_drift({K_GAIN: "70"}, {K_GAIN: "50"}) == {K_GAIN: "70"}


# ---------------------------------------------------------------- câmera fake
class FakeCamera:
    def __init__(self, config=None, probe_codes=None, set_ok=True, fail_first_n=0):
        self.config = dict(config or {})
        self.probe_codes = list(probe_codes) if probe_codes is not None else None
        self.set_ok = set_ok
        self.fail_first_n = fail_first_n
        self.set_calls = 0
        self.get_calls = 0
        self._probe_i = 0

    def device_type(self):
        if self.probe_codes is None:
            return 200
        code = self.probe_codes[min(self._probe_i, len(self.probe_codes) - 1)]
        self._probe_i += 1
        return code

    def get_config(self, name):
        self.get_calls += 1
        return {k: v for k, v in self.config.items() if k.startswith(name)}

    def set_config(self, params):
        self.set_calls += 1
        if self.fail_first_n and self.set_calls <= self.fail_first_n:
            return (False, 0)
        if not self.set_ok:
            return (False, 401)
        self.config.update(params)
        return (True, 200)


def _run(cam, mode="day", **kw):
    return cc.reconcile(cam, PROFILE, "12:00", force_mode=mode, sleep=noop_sleep, **kw)


# ---------------------------------------------------------------- fluxo
def test_reconcile_no_drift_writes_nothing():
    # GainMax já bate; ExposureValue2 lê diferente (auto-varia) mas é NO_VERIFY
    cam = FakeCamera({K_EV: "17.5", K_GAIN: "70"})
    assert _run(cam, "day") == 0
    assert cam.set_calls == 0                     # idempotente de verdade


def test_reconcile_applies_shutter_verify_gain():
    cam = FakeCamera({K_EV: "33.33", K_GAIN: "50"})   # está em night
    assert _run(cam, "day") == 0
    assert cam.config[K_GAIN] == "70"             # gain aplicado + verificado
    assert cam.config[K_EV] == "4"                # exposure foi junto no grupo
    assert cam.set_calls == 1                     # 1 grupo (VideoInOptions)


def test_reconcile_unstable_aborts():
    cam = FakeCamera({K_GAIN: "50"}, probe_codes=[0, 0, 0])
    assert _run(cam) == 2
    assert cam.set_calls == 0 and cam.get_calls == 0


def test_reconcile_write_fails_then_backoff_ok():
    cam = FakeCamera({K_GAIN: "50"}, fail_first_n=1)
    assert _run(cam, "day") == 0
    assert cam.config[K_GAIN] == "70"


def test_reconcile_write_always_fails_returns_1():
    cam = FakeCamera({K_GAIN: "50"}, set_ok=False)
    assert _run(cam, "day") == 1


def test_reconcile_dry_run_writes_nothing():
    cam = FakeCamera({K_GAIN: "50"})
    assert _run(cam, "day", dry_run=True) == 0
    assert cam.set_calls == 0


def test_profile_json_valid():
    from pathlib import Path
    p = Path(cc.__file__).resolve().parent / "cam_profile.json"
    prof = json.loads(p.read_text(encoding="utf-8"))
    assert prof["lighting_enabled"] is False       # IR desligado por padrão (firmware quirk)
    assert prof["shutter"]["day"]["gain_max"] == 70
    assert "night" in prof["shutter"]
