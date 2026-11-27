"""RPA rules shared by the worker and backend notification paths."""


def _rpa_key(value: str | None) -> str:
    raw = (value or "").strip().lower()
    digits = "".join(character for character in raw if character.isdigit())
    return digits or raw.replace(" ", "").replace("-", "")


def is_same_rpa(user_rpa: str | None, detection_rpa: str | None) -> bool:
    user_key = _rpa_key(user_rpa)
    # An active user without an assigned RPA receives every RPA.
    return not user_key or user_key == _rpa_key(detection_rpa)


def format_rpa_label(rpa: str | None) -> str:
    value = (rpa or "").strip()
    if not value:
        return "RPA ?"
    if value.lower().startswith("rpa"):
        return value
    return f"RPA {value}"
