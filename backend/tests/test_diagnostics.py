import json
import logging
from pathlib import Path

from sensogrid.config import Settings
from sensogrid.diagnostics import capture_logs, redact


def test_diagnostic_logs_redact_secrets_and_keep_tracebacks(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, influx_token="private-influx-token")
    with capture_logs(settings):
        try:
            raise RuntimeError("failed with private-influx-token")
        except RuntimeError:
            logging.getLogger("sensogrid.runtime").exception("BLE failure token=another-secret")
    content = (tmp_path / "diagnostics/app.jsonl").read_text(encoding="utf-8")
    assert "private-influx-token" not in content
    assert "another-secret" not in content
    assert "RuntimeError" in content
    assert "Traceback" in content
    records = [json.loads(line) for line in content.splitlines()]
    assert records[-1]["logger"] == "sensogrid.runtime"


def test_redaction_removes_url_credentials_query_and_bearer() -> None:
    value = redact(
        'https://user:pass@example.com/path?token=secret Bearer abcdef "password": "hidden"'
    )
    for secret in ["user:pass", "token=secret", "abcdef", "hidden"]:
        assert secret not in value
    assert "example.com/path" in value


def test_redaction_removes_complete_basic_authorization_and_cookie_headers() -> None:
    value = redact(
        "Authorization: Basic dXNlcjpwYXNz\nCookie: session=a123; other=b456\npublic error"
    )
    assert "dXNlcjpwYXNz" not in value
    assert "a123" not in value and "b456" not in value
    assert "public error" in value


def test_diagnostic_logs_rotate_instead_of_growing_without_bound(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    with capture_logs(settings):
        for _ in range(70):
            logging.getLogger("sensogrid.runtime").warning("x" * 16000)
    files = list((tmp_path / "diagnostics").glob("app.jsonl*"))
    assert len(files) > 1
    assert sum(path.stat().st_size for path in files) < 4 * 550000
