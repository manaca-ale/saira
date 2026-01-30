# src/ingester/local/ui_selector.py
"""Find and tap UI elements by resource-id, content-desc, or text via uiautomator dump."""
import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET

from . import adb_adapter
from .. import config

logger = logging.getLogger(__name__)

_DUMP_TIMEOUT = 60


def find_element(
    device_id: str,
    resource_id: str | None = None,
    content_desc: str | None = None,
    text: str | None = None,
    timeout_s: float = _DUMP_TIMEOUT,
) -> dict | None:
    """Find a UI element via uiautomator dump.

    Returns {"center": {"x": int, "y": int}, "bounds": str} or None.
    At least one of resource_id, content_desc, or text must be provided.
    """
    remote_xml = "/sdcard/saira_ui_dump.xml"
    fd, local_xml = tempfile.mkstemp(prefix="ui_dump_", suffix=".xml")
    os.close(fd)

    try:
        dump_result = adb_adapter._run_command(
            ["-s", device_id, "shell", "uiautomator", "dump", remote_xml],
            timeout_s=timeout_s,
            check=False,
        )
        if dump_result.returncode != 0:
            logger.warning(f"uiautomator dump failed: {dump_result.stderr}")
            return None

        adb_adapter._run_command(
            ["-s", device_id, "pull", remote_xml, local_xml],
            timeout_s=30,
            check=False,
        )
        adb_adapter._run_command(
            ["-s", device_id, "shell", "rm", remote_xml],
            timeout_s=10,
            check=False,
        )

        return _search_xml(local_xml, resource_id, content_desc, text)
    except Exception as exc:
        logger.warning(f"find_element failed: {exc}")
        return None
    finally:
        try:
            os.unlink(local_xml)
        except OSError:
            pass


def tap_element(
    device_id: str,
    resource_id: str | None = None,
    content_desc: str | None = None,
    text: str | None = None,
    fallback_coords: dict | None = None,
    timeout_s: float = _DUMP_TIMEOUT,
) -> bool:
    """Find an element and tap its center. Falls back to coords if element not found."""
    element = find_element(device_id, resource_id, content_desc, text, timeout_s)

    if element and element.get("center"):
        cx, cy = element["center"]["x"], element["center"]["y"]
        logger.info(f"tap_element: found via selector at ({cx}, {cy})")
        adb_adapter.tap(device_id, cx, cy, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        return True

    if fallback_coords:
        fx, fy = fallback_coords["x"], fallback_coords["y"]
        logger.info(f"tap_element: selector miss, using fallback ({fx}, {fy})")
        adb_adapter.tap(device_id, fx, fy, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        return True

    logger.warning("tap_element: no element found and no fallback coords")
    return False


def _search_xml(
    xml_path: str,
    resource_id: str | None,
    content_desc: str | None,
    text: str | None,
) -> dict | None:
    """Search parsed XML for a matching node."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        logger.warning(f"XML parse error: {exc}")
        return None

    for node in tree.iter("node"):
        if resource_id and node.get("resource-id") == resource_id:
            return _node_to_result(node)
        if content_desc and node.get("content-desc") == content_desc:
            return _node_to_result(node)
        if text and node.get("text") == text:
            return _node_to_result(node)

    return None


def _node_to_result(node: ET.Element) -> dict:
    bounds_str = node.get("bounds", "")
    bounds = _parse_bounds(bounds_str)
    center = None
    if bounds:
        x1, y1, x2, y2 = bounds
        center = {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2}
    return {"bounds": bounds_str, "center": center}


def _parse_bounds(bounds_str: str) -> tuple[int, int, int, int] | None:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
    if not m:
        return None
    return tuple(int(v) for v in m.groups())
