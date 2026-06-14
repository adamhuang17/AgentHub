from urllib import error, request

from tests.support import WEB_BASE_URL


def test_web_boot():
    try:
        with request.urlopen(WEB_BASE_URL, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except error.URLError as exc:
        raise AssertionError(f"Cannot reach AgentHub web app at {WEB_BASE_URL}: {exc}") from exc
    assert "<html" in body.lower()
    assert "agenthub" in body.lower() or "root" in body.lower()
