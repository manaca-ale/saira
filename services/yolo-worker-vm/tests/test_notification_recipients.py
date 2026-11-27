"""Characterize the recipients of a worker-created detection."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from worker import db


@pytest.mark.parametrize(
    ("detection_rpa", "expected_ids"),
    [
        ("RPA-3", [1, 2, 3, 4, 5, 6]),
        (None, [1, 2, 3]),
        ("sul oeste", [1, 2, 3, 8]),
        ("RPA 03", [1, 2, 3, 9]),
        ("RPA ٣", [1, 2, 3, 10]),
    ],
)
def test_insert_notifications_selects_active_users_by_rpa(monkeypatch, detection_rpa, expected_ids):
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchall.return_value = [
        (1, None), (2, " "), (3, " - "), (4, "3"), (5, " rpa 3 "), (6, "RPA-3"),
        (7, "RPA-4"), (8, " Sul-Oeste "), (9, "03"), (10, "٣"),
    ]
    monkeypatch.setattr(db, "_get_conn", lambda: conn)
    monkeypatch.setattr(db, "_put_conn", MagicMock())
    detection = SimpleNamespace(id=uuid4(), timestamp=datetime.now(timezone.utc))
    camera = SimpleNamespace(rpa=detection_rpa, logradouro="Av Norte", bairro="Torre")

    assert db.insert_notifications(detection, camera) == len(expected_ids)

    query, *inserts = cursor.execute.call_args_list
    assert query.args == ("SELECT id, rpa FROM users WHERE is_active = true",)
    assert [insert.args[1][1] for insert in inserts] == expected_ids
    assert all(insert.args[1][2] == detection.id for insert in inserts)
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
