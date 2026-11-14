"""The verify script fails a run that changes the checkout or reaches the network."""

import asyncio
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SKILL = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "verify-trace"


def load_verify() -> ModuleType:
    sys.path.insert(0, str(SKILL))
    loader = importlib.machinery.SourceFileLoader("verify_trace_script", str(SKILL / "verify"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # The script re-executes itself under uv unless it runs from the checkout's .venv.
    monkeypatch.setattr(sys, "prefix", str(SKILL.parents[2] / ".venv"))
    module = load_verify()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def test_checkout_changes_report_a_file_a_directory_and_a_git_fact(
    verify: ModuleType, tmp_path: Path
) -> None:
    before = verify.checkout_state()
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")
    (tmp_path / "stray_dir").mkdir()
    subprocess.run(["git", "config", "--local", "probe.key", "1"], cwd=tmp_path, check=True)
    changes: list[str] = verify.checkout_changes(before, verify.checkout_state())
    assert "stray.txt" in changes
    assert "stray_dir/" in changes
    assert "git config changed" in changes
    assert verify.checkout_changes(before, before) == []


def test_the_audit_hook_refuses_and_logs_an_external_connection(
    verify: ModuleType, tmp_path: Path
) -> None:
    drives = sys.modules["drives"]
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(drives.GUARD, encoding="utf-8")
    log = tmp_path / "network.log"
    log.touch()
    env = {"PYTHONPATH": str(guard), "TRACE_VERIFY_NETWORK_LOG": str(log)}
    code = "import socket; socket.create_connection(('192.0.2.1', 80), 1)"
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert done.returncode != 0
    assert "192.0.2.1" in log.read_text(encoding="utf-8")


def test_a_network_attempt_fails_a_drive_that_passed(verify: ModuleType, tmp_path: Path) -> None:
    log = tmp_path / "network.log"
    log.write_text("connect example.invalid\n", encoding="utf-8")
    ctx = SimpleNamespace(env={"TRACE_VERIFY_NETWORK_LOG": str(log)}, stop_processes=lambda: None)

    async def passing(_ctx: object) -> str:
        return "fine"

    result, _seconds, detail = asyncio.run(verify.run_one("probe", passing, ctx, 5.0))
    assert result == "FAIL"
    assert "example.invalid" in detail
