from pathlib import Path


def _text_files(*roots):
    for root in roots:
        for path in Path(root).rglob("*"):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            if path.suffix.lower() in {".py", ".md", ".txt", ".mjs", ".js"}:
                yield path


def test_legacy_planning_terms_are_absent_from_active_paths():
    terms = [
        "planner" + "_decision",
        "Planner" + "Gateway",
        "Planner" + "Decision",
        "AGENTHUB_ENABLE_TEST_" + "PLANNER_BACKEND",
        "AGENTHUB_" + "PLANNER_BACKEND",
    ]
    offenders = []
    for path in _text_files("services/api/app", "tests/acceptance", "tests/contract"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(term in text for term in terms):
            offenders.append(str(path))

    assert offenders == []


def test_legacy_pin_endpoints_are_absent_from_product_and_tests():
    terms = [
        "legacy_message" + "_pin",
        "list_legacy_message" + "_pins",
        "/" + "pins",
        "messages/" + ".*/" + "pin",
    ]
    offenders = []
    for path in _text_files("services/api/app", "tests"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(term in text for term in terms):
            offenders.append(str(path))

    assert offenders == []
