from pathlib import Path


def test_compose_file_exists():
    root = Path(__file__).resolve().parents[2]
    compose = root / "infra" / "compose.yml"
    assert compose.exists(), "infra/compose.yml is required for reproducible boot"
    content = compose.read_text(encoding="utf-8")
    assert "postgres" in content.lower()
    assert "redis" in content.lower()
    assert "api" in content.lower()
