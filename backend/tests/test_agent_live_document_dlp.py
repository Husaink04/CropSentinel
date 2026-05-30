from __future__ import annotations

import sys
import zipfile
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_live_parser_extracts_docx_text(tmp_path):
    from file_tracker import _Handler

    docx_path = tmp_path / "sample.docx"
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Employee SSN 123-45-6789</w:t></w:r></w:p></w:body>
            </w:document>""",
        )

    handler = _Handler("machine-1", lambda *_args, **_kwargs: None)
    parsed = handler._extract_live_text(str(docx_path), ".docx", docx_path.stat().st_size)

    assert parsed is not None
    assert parsed["parser_type"] == "docx"
    assert "123-45-6789" in parsed["content"]


def test_scan_file_v2_uses_provided_file_hash():
    from dlp_engine import DLPEngine

    engine = DLPEngine(enabled=True, risk_thresholds={"low": 1, "medium": 3, "high": 7})
    result = engine.scan_file_v2(
        file_path="C:/tmp/sample.txt",
        content="Employee SSN 123-45-6789",
        destination="usb",
        file_size=128,
        file_ext=".txt",
        file_hash="binary-file-hash",
    )

    assert result is not None
    assert result["file_hash"] == "binary-file-hash"


def test_baseline_parser_extracts_nested_zip_text():
    from baseline_inventory import BaselineInventoryConfig, BaselineParser

    parser = BaselineParser(BaselineInventoryConfig())
    import io

    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as inner:
        inner.writestr("secret.txt", "Confidential customer export 987654")

    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("nested.zip", nested.getvalue())

    text = parser._extract_zip_bytes(outer.getvalue(), 0)
    assert "secret.txt" in text
    assert "987654" in text


def test_baseline_parser_extracts_eml_attachment_text(tmp_path):
    from baseline_inventory import BaselineInventoryConfig, BaselineParser

    parser = BaselineParser(BaselineInventoryConfig())
    eml_path = tmp_path / "attachment.eml"
    eml_path.write_bytes(
        b"Subject: payroll package\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"sep\"\r\n\r\n"
        b"--sep\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"See attached.\r\n"
        b"--sep\r\n"
        b"Content-Type: text/plain; name=\"ssn.txt\"\r\n"
        b"Content-Disposition: attachment; filename=\"ssn.txt\"\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"RW1wbG95ZWUgU1NOIDEyMy00NS02Nzg5\r\n"
        b"--sep--\r\n"
    )

    result = parser.inspect(str(eml_path), ".eml", eml_path.stat().st_size)
    assert result["inspect_status"] == "inspected"
    assert result["parser_type"] == "eml"
    assert "ssn.txt" in result["extracted_text"]
    assert "123-45-6789" in result["extracted_text"]


def test_print_event_emits_contextual_dlp_alert():
    from file_tracker import _Handler

    events = []
    handler = _Handler("machine-1", lambda kind, data: events.append((kind, data)))
    handler._recent_sensitive_records = [
        {
            "captured_at": 9999999999,
            "file_path": r"C:\Users\lab\Documents\payroll.xlsx",
            "file_name": "payroll.xlsx",
            "file_hash": "hash-payroll",
            "content_fingerprint": "content-payroll",
            "enterprise_label": "Confidential",
            "findings": [{"type": "ssn", "count": 2}],
            "risk_level": "high",
            "risk_score": 10,
        }
    ]

    handler.handle_print_event(
        {
            "timestamp": "2026-05-11T10:00:00+00:00",
            "document": "payroll.xlsx",
            "printer": "HP LaserJet",
            "pages": 2,
        }
    )

    assert events
    kind, payload = events[0]
    assert kind == "dlp_alert"
    assert payload["destination_type"] == "print"
    assert payload["file_name"] == "payroll.xlsx"
    assert payload["findings"][0]["type"] == "ssn"


def test_browser_upload_event_emits_contextual_dlp_alert():
    from file_tracker import _Handler

    events = []
    handler = _Handler("machine-1", lambda kind, data: events.append((kind, data)))
    handler._recent_sensitive_records = [
        {
            "captured_at": 9999999999,
            "file_path": r"C:\Users\lab\Documents\customer.csv",
            "file_name": "customer.csv",
            "file_hash": "hash-customer",
            "content_fingerprint": "content-customer",
            "enterprise_label": "Sensitive",
            "findings": [{"type": "email", "count": 20}],
            "risk_level": "medium",
            "risk_score": 6,
        }
    ]

    handler.handle_browser_upload_event(
        {
            "timestamp": "2026-05-11T10:05:00+00:00",
            "domain": "mail.google.com",
            "url": "https://mail.google.com/mail/u/0/#inbox",
            "browser": "Chrome",
        }
    )

    assert events
    kind, payload = events[0]
    assert kind == "dlp_alert"
    assert payload["destination_type"] == "email"
    assert payload["destination_label"] == "mail.google.com"
    assert payload["file_name"] == "customer.csv"


def test_clipboard_text_emits_blocked_dlp_alert(monkeypatch):
    import sys
    import types

    sys.modules["pyperclip"] = types.SimpleNamespace(copy=lambda value: None)

    from file_tracker import _Handler

    events = []
    handler = _Handler("machine-1", lambda kind, data: events.append((kind, data)))
    handler.set_dlp_context = None
    handler._runtime_context_getter = lambda: {
        "policy": {
            "rollout_mode": "hard_block",
            "rules": [],
            "classifiers": [],
            "exceptions": [],
        },
        "actor_username": "labuser",
    }

    handler.handle_clipboard_text(
        {
            "timestamp": "2026-05-11T10:10:00+00:00",
            "text": "Employee SSN 123-45-6789",
            "content_fingerprint": "clip-fingerprint",
        }
    )

    assert events
    kind, payload = events[0]
    assert kind == "dlp_alert"
    assert payload["destination_type"] == "clipboard"
    assert payload["action_result"] in {"blocked", "warning_shown", "observed"}
    assert payload["findings"][0]["type"] == "ssn"
