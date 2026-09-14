"""Invoke the Codex CLI to perform the judgment core of the daily run."""

from __future__ import annotations

import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger()


class CodexRunError(Exception):
    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def load_prompt(prompt_path: Path, *, work_dir: Path) -> str:
    """Load the daily-run prompt template, substituting the work_dir path."""
    template = prompt_path.read_text(encoding="utf-8")
    return template.replace("{{WORK_DIR}}", str(work_dir))


def build_codex_command(
    *,
    codex_bin: str,
    prompt: str,
    work_dir: Path,
    package_root: Path,
    model: str | None = None,
) -> list[str]:
    # Note: --ask-for-approval is a global flag and must precede `exec`
    # (codex 0.145 rejects `codex exec --ask-for-approval ...`).
    command = [
        codex_bin,
        "--ask-for-approval",
        "never",
        "exec",
        "--sandbox",
        "workspace-write",
        # morning_research / research_processing are not git checkouts.
        "--skip-git-repo-check",
        "--cd",
        str(work_dir),
        "--add-dir",
        str(package_root),
    ]
    if model:
        command.extend(["-m", model])
    command.append(prompt)
    return command


def run_codex(
    *,
    codex_bin: str,
    prompt: str,
    work_dir: Path,
    package_root: Path,
    timeout_seconds: int,
    model: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `codex exec` with the given prompt and directories, raising on failure."""
    command = build_codex_command(
        codex_bin=codex_bin,
        prompt=prompt,
        work_dir=work_dir,
        package_root=package_root,
        model=model,
    )

    logger.info(
        "Running codex exec",
        work_dir=str(work_dir),
        package_root=str(package_root),
        model=model,
        timeout_seconds=timeout_seconds,
        command=command[:-1] + ["<prompt>"],
    )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _write_codex_logs(
            work_dir,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        )
        raise CodexRunError(
            f"codex exec timed out after {timeout_seconds}s",
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        ) from exc
    except FileNotFoundError as exc:
        raise CodexRunError(f"codex binary not found: {codex_bin}") from exc

    _write_codex_logs(work_dir, stdout=result.stdout, stderr=result.stderr)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if len(detail) > 2000:
            detail = detail[:2000] + "..."
        raise CodexRunError(
            f"codex exec exited with code {result.returncode}: {detail}",
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    logger.info("codex exec completed", returncode=result.returncode)
    return result


def _write_codex_logs(work_dir: Path, *, stdout: str, stderr: str) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "codex_stdout.log").write_text(stdout or "", encoding="utf-8")
    (work_dir / "codex_stderr.log").write_text(stderr or "", encoding="utf-8")
