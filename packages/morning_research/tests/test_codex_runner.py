"""Codex runner command construction tests."""

from __future__ import annotations

from pathlib import Path

from morning_research.codex_runner import build_codex_command


def test_build_codex_command_includes_skip_git_repo_check(tmp_path: Path) -> None:
    work = tmp_path / "work"
    root = tmp_path / "pkg"
    work.mkdir()
    root.mkdir()
    cmd = build_codex_command(
        codex_bin="codex",
        prompt="do the thing",
        work_dir=work,
        package_root=root,
    )
    assert cmd[:4] == ["codex", "--ask-for-approval", "never", "exec"]
    assert "--skip-git-repo-check" in cmd
    assert "--cd" in cmd
    assert str(work) in cmd
    # Must not appear after `exec` (CLI rejects that form).
    exec_idx = cmd.index("exec")
    assert "--ask-for-approval" not in cmd[exec_idx + 1 :]
