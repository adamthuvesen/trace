"""The verify script fails a run that changes the checkout or reaches the network."""

import asyncio
import importlib.machinery
import importlib.util
import os
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
    subprocess.run(["git", "init", "-q", str(tmp_path)], env=clean_git_env(), check=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def clean_git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git_in(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        env=clean_git_env(),
        check=True,
        capture_output=True,
    )


def test_checkout_changes_report_a_file_and_a_directory(verify: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "edited.txt").write_text("one", encoding="utf-8")
    (tmp_path / "resized.txt").write_text("one", encoding="utf-8")
    (tmp_path / "touched.txt").write_text("one", encoding="utf-8")
    before = verify.checkout_state()
    stat = (tmp_path / "resized.txt").stat()
    (tmp_path / "resized.txt").write_text("longer", encoding="utf-8")
    os.utime(tmp_path / "resized.txt", ns=(stat.st_atime_ns, stat.st_mtime_ns))
    stat = (tmp_path / "touched.txt").stat()
    os.utime(tmp_path / "touched.txt", ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")
    (tmp_path / "stray_dir").mkdir()
    changes: list[str] = verify.checkout_changes(before, verify.checkout_state())
    assert "stray.txt" in changes
    assert "stray_dir/" in changes
    assert "resized.txt" in changes
    assert "touched.txt" in changes
    assert verify.checkout_changes(before, before) == []


GIT_FACT_CHANGES = {
    "HEAD commit": [["commit", "-q", "--allow-empty", "-m", "next"]],
    "HEAD branch": [["symbolic-ref", "HEAD", "refs/heads/other"]],
    "git index": [["rm", "-q", "--cached", "tracked.txt"]],
    "git index flags": [["update-index", "--assume-unchanged", "tracked.txt"]],
    "git config": [["config", "--local", "probe.key", "1"]],
    "git worktree config": [["config", "--worktree", "probe.key", "1"]],
}


def test_every_git_fact_is_tested(verify: ModuleType) -> None:
    assert set(GIT_FACT_CHANGES) == set(verify.GIT_FACTS)


@pytest.mark.parametrize("fact", sorted(GIT_FACT_CHANGES))
def test_checkout_changes_report_each_git_fact(
    verify: ModuleType, tmp_path: Path, fact: str
) -> None:
    (tmp_path / "tracked.txt").write_text("x", encoding="utf-8")
    git_in(tmp_path, "add", "tracked.txt")
    git_in(tmp_path, "commit", "-q", "-m", "first")
    git_in(tmp_path, "config", "extensions.worktreeConfig", "true")
    before = verify.checkout_state()
    for args in GIT_FACT_CHANGES[fact]:
        git_in(tmp_path, *args)
    changes: list[str] = verify.checkout_changes(before, verify.checkout_state())
    assert f"{fact} changed" in changes


def stub_main(
    verify: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    effect: str,
) -> int:
    """Run main() on a fake drive; the real model cache and preflight are not needed.

    effect: "clean", "stray_file", "fail" (drive fails), "crash" or "network" (control only).
    """
    drives = sys.modules["drives"]
    log = tmp_path / "network.log"
    log.touch()

    async def fake_drive(ctx: SimpleNamespace) -> str:
        if effect == "stray_file":
            (tmp_path / "stray.txt").write_text("x", encoding="utf-8")
        if effect == "fail":
            raise drives.Failure("planted failure")
        return "fine"

    async def fake_control(ctx: SimpleNamespace) -> str:
        await fake_drive(ctx)
        if effect == "crash":
            raise RuntimeError("planted crash")
        if effect == "network":
            log.write_text("socket.connect: 192.0.2.1\n", encoding="utf-8")
        raise drives.Failure(drives.CONTROL_FAILURE + " got nothing")

    fake = SimpleNamespace(run=fake_drive, timeout=5.0, paths=[])
    monkeypatch.setattr(verify, "DRIVES", {"fake": fake})
    monkeypatch.setattr(verify, "control", fake_control)
    monkeypatch.setattr(
        verify, "child_env", lambda _scratch: {"TRACE_VERIFY_NETWORK_LOG": str(log)}
    )
    monkeypatch.setattr(
        verify,
        "Context",
        lambda *, env, **_: SimpleNamespace(env=env, stop_processes=lambda: None),
    )
    monkeypatch.setattr(verify, "preflight", lambda _env, _scratch: None)
    return verify.main([command])


@pytest.mark.parametrize("command", ["fake", "control"])
def test_main_passes_a_clean_run(
    verify: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert stub_main(verify, tmp_path, monkeypatch, command, "clean") == 0


@pytest.mark.parametrize(
    ("command", "effect"),
    [
        ("fake", "stray_file"),
        ("fake", "fail"),
        ("control", "stray_file"),
        ("control", "crash"),
        ("control", "network"),
    ],
)
def test_main_fails_a_bad_run(
    verify: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    effect: str,
) -> None:
    assert stub_main(verify, tmp_path, monkeypatch, command, effect) == 1


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
