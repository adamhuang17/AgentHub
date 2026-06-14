from pathlib import Path
import subprocess


def test_module_boundary_directories_exist():
    root = Path(__file__).resolve().parents[2]
    expected = [
        "services/api/app/conversations",
        "services/api/app/agents",
        "services/api/app/orchestration",
        "services/api/app/execution",
        "services/api/app/artifacts",
        "services/api/app/permissions",
    ]
    missing = [path for path in expected if not (root / path).exists()]
    assert not missing, f"Missing module boundary directories: {missing}"


def test_product_path_does_not_restore_keyword_intent_classifier():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["rg", "-n", "intent_classifier|classify_message", "services/api/app"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout
