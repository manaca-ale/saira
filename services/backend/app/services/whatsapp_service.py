import base64
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Protocol

import requests
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings

logger = logging.getLogger(__name__)


class WhatsAppAdapter(Protocol):
    def send_text(self, to: str, message: str) -> bool:
        ...

    def send_image(self, to: str, image_bytes: bytes, filename: str, caption: str = "") -> bool:
        ...


def _normalize_phone(to: str) -> str:
    raw = (to or "").strip()
    if not raw:
        raise ValueError("Phone number is required")
    if raw.endswith("@c.us"):
        return raw
    digits = re.sub(r"\D", "", raw)
    if not digits:
        raise ValueError("Invalid phone number")
    return f"{digits}@c.us"


def _to_float(value: object, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return fallback


def _format_rpa_key(value: str | None) -> str:
    raw = (value or "").strip().lower()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits:
        return digits
    return raw.replace(" ", "").replace("-", "")


def _build_detection_link(detection_id: str) -> str:
    base = settings.WEB_APP_URL.rstrip("/")
    return f"{base}/detections?detection_id={detection_id}"


def _build_occurrence_png(detection: object) -> bytes:
    width, height = 1080, 1280
    canvas = Image.new("RGB", (width, height), "#F4F7F8")
    draw = ImageDraw.Draw(canvas)
    title_font = ImageFont.load_default()
    body_font = ImageFont.load_default()

    # Header block
    draw.rounded_rectangle((40, 40, width - 40, 180), radius=24, fill="#1A1A1A")
    draw.text((70, 85), "SAIRA - Nova Ocorrencia", fill="#FFFFFF", font=title_font)

    # Main card
    draw.rounded_rectangle((40, 220, width - 40, height - 60), radius=24, fill="#FFFFFF", outline="#DDE3E6", width=2)

    timestamp = getattr(detection, "timestamp", None)
    if isinstance(timestamp, datetime):
        timestamp_label = timestamp.strftime("%d/%m/%Y %H:%M")
    else:
        timestamp_label = "N/A"

    info_lines = [
        ("ID", str(getattr(detection, "id", "N/A"))),
        ("Data/Hora", timestamp_label),
        ("RPA", str(getattr(detection, "rpa", "N/A"))),
        ("Bairro", str(getattr(detection, "bairro", "N/A"))),
        ("Logradouro", str(getattr(detection, "logradouro", "N/A"))),
        ("Tipo de residuo", str(getattr(detection, "waste_type", "N/A"))),
        ("Volume (m3)", f"{_to_float(getattr(detection, 'volume_m3', 0.0)):.2f}"),
        ("Status", str(getattr(detection, "status", "Pendente"))),
    ]

    y = 270
    for label, value in info_lines:
        draw.text((80, y), f"{label}:", fill="#6B7280", font=body_font)
        draw.text((320, y), value, fill="#111827", font=body_font)
        y += 90

    draw.rounded_rectangle((80, height - 220, width - 80, height - 110), radius=16, fill="#ECFCCB")
    draw.text((110, height - 180), "Acesse o painel para tratar esta ocorrencia.", fill="#3F6212", font=body_font)

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


@dataclass
class WahaAdapter:
    base_url: str
    api_key: str
    session_name: str = "default"
    timeout_seconds: int = 15

    def _post(self, path: str, payload: dict, *, log_error: bool = True) -> tuple[bool, int | None]:
        url = f"{self.base_url.rstrip('/')}{path}"
        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=self.timeout_seconds
            )
            if response.ok:
                return True, response.status_code
            if log_error:
                logger.error(
                    "WAHA request failed",
                    extra={
                        "status_code": response.status_code,
                        "response": response.text,
                        "path": path,
                    },
                )
            return False, response.status_code
        except requests.RequestException:
            if log_error:
                logger.exception("Failed to call WAHA endpoint %s", path)
            return False, None

    def _post_first_available(self, paths: list[str], payload: dict) -> bool:
        """Try multiple route shapes and fallback only on not-found/method errors."""
        total = len(paths)
        for idx, path in enumerate(paths):
            is_last = idx == total - 1
            ok, status_code = self._post(path, payload, log_error=is_last)
            if ok:
                return True
            if status_code not in {404, 405}:
                return False
        return False

    def send_text(self, to: str, message: str) -> bool:
        chat_id = _normalize_phone(to)
        payload = {"chatId": chat_id, "text": message, "session": self.session_name}
        return self._post_first_available(
            ["/api/sendText", f"/api/{self.session_name}/sendText"],
            payload,
        )

    def send_image(self, to: str, image_bytes: bytes, filename: str, caption: str = "") -> bool:
        chat_id = _normalize_phone(to)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "chatId": chat_id,
            "caption": caption,
            "session": self.session_name,
            "file": {
                "mimetype": "image/png",
                "filename": filename,
                "data": encoded,
            },
        }
        return self._post_first_available(
            ["/api/sendImage", f"/api/{self.session_name}/sendImage", f"/api/{self.session_name}/sendFile"],
            payload,
        )


@dataclass
class MetaAdapter:
    api_token: str
    phone_id: str

    def send_text(self, to: str, message: str) -> bool:
        # TODO: Implement Meta Cloud API adapter.
        logger.warning("Meta provider selected, but adapter is not implemented yet")
        return False

    def send_image(self, to: str, image_bytes: bytes, filename: str, caption: str = "") -> bool:
        # TODO: Implement Meta Cloud API adapter.
        logger.warning("Meta provider selected, but adapter is not implemented yet")
        return False


class WhatsAppService:
    def __init__(self) -> None:
        provider = (settings.WHATSAPP_PROVIDER or "waha").strip().lower()
        self.provider = provider
        if provider == "waha":
            self.adapter: WhatsAppAdapter = WahaAdapter(
                settings.WAHA_BASE_URL,
                settings.WAHA_API_KEY,
                settings.WAHA_SESSION_NAME,
            )
        elif provider == "meta":
            self.adapter = MetaAdapter(settings.META_API_TOKEN, settings.META_PHONE_ID)
        else:
            logger.warning("Unknown WhatsApp provider '%s'; defaulting to WAHA", provider)
            self.provider = "waha"
            self.adapter = WahaAdapter(
                settings.WAHA_BASE_URL,
                settings.WAHA_API_KEY,
                settings.WAHA_SESSION_NAME,
            )

    def send_message(self, to: str, message: str) -> bool:
        try:
            return self.adapter.send_text(to, message)
        except ValueError:
            logger.exception("Invalid WhatsApp payload")
            return False
        except Exception:
            logger.exception("Unexpected error while sending WhatsApp message")
            return False

    def send_occurrence_alert(self, users: Iterable[object], detection: object) -> int:
        detection_id = str(getattr(detection, "id", ""))
        link = _build_detection_link(detection_id)
        rpa = str(getattr(detection, "rpa", "N/A"))
        bairro = str(getattr(detection, "bairro", "N/A"))
        logradouro = str(getattr(detection, "logradouro", "N/A"))
        volume = _to_float(getattr(detection, "volume_m3", 0.0))
        waste_type = str(getattr(detection, "waste_type", "N/A"))

        text_message = (
            "Nova ocorrencia detectada no SAIRA.\n"
            f"RPA: {rpa}\n"
            f"Local: {logradouro}, {bairro}\n"
            f"Tipo: {waste_type} | Volume: {volume:.2f} m3\n"
            f"Acesse o sistema: {link}"
        )

        image_bytes = _build_occurrence_png(detection)
        image_caption = f"Ocorrencia {detection_id} - SAIRA"
        delivered = 0

        for user in users:
            phone = (getattr(user, "phone", "") or "").strip()
            if not phone:
                continue

            image_sent = self.adapter.send_image(
                phone, image_bytes, "ocorrencia.png", caption=image_caption
            )
            if not image_sent:
                logger.warning(
                    "WhatsApp image delivery unavailable; sending text-only alert",
                    extra={"phone": phone, "detection_id": detection_id},
                )

            text_sent = self.adapter.send_text(phone, text_message)
            if text_sent:
                delivered += 1

        return delivered

    @staticmethod
    def is_same_rpa(user_rpa: str | None, detection_rpa: str | None) -> bool:
        return _format_rpa_key(user_rpa) == _format_rpa_key(detection_rpa)
