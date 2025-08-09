import subprocess

def _run(cmd: list[str]) -> int:
    return subprocess.run(cmd, capture_output=True).returncode

def test_black():
    assert _run(["black", "--check", "."]) == 0

def test_isort():
    assert _run(["isort", "--check-only", "."]) == 0

def test_ruff():
    assert _run(["ruff", "check", "."]) == 0
