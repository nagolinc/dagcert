"""External, fail-closed verification of Python operation exception freedom.

Dagcert does not implement a Python verifier.  It invokes a digest-pinned Nagini/Viper
toolchain in a network-disabled container and accepts only an explicit successful proof.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired, run
from typing import Iterable


NAGINI_VERSION = "1.3.1"
NAGINI_IMAGE_REPOSITORY = "ghcr.io/bigtalk-org/docker-nagini"
NAGINI_IMAGE_DIGEST = (
    "sha256:b5cf0ca97ab21dd6c1f8daa8384235bb7a88fecf364bb7a74f42b2a1c26274e0"
)
NAGINI_IMAGE = f"{NAGINI_IMAGE_REPOSITORY}@{NAGINI_IMAGE_DIGEST}"
NAGINI_BACKEND = "silicon"
NAGINI_TIMEOUT_SECONDS = 180


class PythonVerificationError(ValueError):
    pass


_CACHE: dict[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]], dict[str, object]] = {}


def verify_exception_freedom(
    source_root: str | Path,
    files: Iterable[str],
    symbols_by_file: dict[str, tuple[str, ...]],
    *,
    source_fingerprint: str,
) -> dict[str, object]:
    """Prove that bound Python modules have no undeclared exceptional exits.

    The complete bound module is verified, rather than asking Nagini to select only a named
    function.  That prevents an operation from hiding unsafe local helpers in the same file.
    Imported application code must also be available below ``source_root`` and translatable by
    Nagini; missing or unsupported code is a refusal, not a skipped check.
    """

    root = Path(source_root).resolve()
    normalized_files = tuple(sorted(set(files)))
    if not normalized_files:
        raise PythonVerificationError("Nagini received no bound Python source files")
    symbol_key = tuple(
        (path, symbol)
        for path in normalized_files
        for symbol in sorted(symbols_by_file.get(path, ()))
    )
    cache_key = (source_fingerprint, normalized_files, symbol_key)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    stub_root = Path(__file__).resolve().parent / "nagini_stubs"
    if not (stub_root / "dagcert" / "runtime.pyi").is_file():
        raise PythonVerificationError("Dagcert's sealed Nagini runtime stub is missing")

    version = _read_nagini_version()
    if version != NAGINI_VERSION:
        raise PythonVerificationError(
            f"pinned Nagini image reported version {version!r}, expected {NAGINI_VERSION!r}"
        )

    verified_files: list[dict[str, object]] = []
    for relative in normalized_files:
        source = (root / relative).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise PythonVerificationError(
                f"Nagini source path escapes source root: {relative}"
            ) from exc
        if not source.is_file():
            raise PythonVerificationError(f"Nagini source file does not exist: {relative}")
        container_path = "/code/" + Path(relative).as_posix()
        command = [
            "docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "256", "--memory", "1g", "--cpus", "2",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "-v", f"{root}:/code:ro",
            "-v", f"{stub_root}:/tmp/dagcert-stubs:ro",
            NAGINI_IMAGE,
            "--verifier", NAGINI_BACKEND,
            "--base-dir", "/tmp/dagcert-stubs",
            container_path,
        ]
        completed = _run(command, label=f"Nagini verification of {relative}")
        output = "\n".join(
            value.strip() for value in (completed.stdout, completed.stderr) if value.strip()
        )
        if completed.returncode != 0 or "Verification successful" not in output:
            detail = output[-12000:] if output else f"exit status {completed.returncode}"
            raise PythonVerificationError(
                f"Nagini could not prove {relative} exception-free:\n{detail}"
            )
        verified_files.append({
            "path": relative,
            "sha256": sha256(source.read_bytes()).hexdigest(),
            "symbols": list(sorted(symbols_by_file.get(relative, ()))),
            "module_scope": "complete-file",
            "result": "proved",
        })

    result: dict[str, object] = {
        "checker": "nagini",
        "version": version,
        "proof_obligation": "no-undeclared-exceptional-exit",
        "backend": NAGINI_BACKEND,
        "container_image": NAGINI_IMAGE_REPOSITORY,
        "container_digest": NAGINI_IMAGE_DIGEST,
        "network": "disabled",
        "source_mount": "read-only",
        "timeout_seconds": NAGINI_TIMEOUT_SECONDS,
        "source_fingerprint": source_fingerprint,
        "files": verified_files,
    }
    _CACHE[cache_key] = dict(result)
    return result


def _read_nagini_version() -> str:
    command = [
        "docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "64", "--memory", "256m", "--cpus", "1",
        "--entrypoint", "python", NAGINI_IMAGE,
        "-c", "import importlib.metadata; print(importlib.metadata.version('nagini'))",
    ]
    completed = _run(command, label="Nagini version check")
    version = completed.stdout.strip()
    if completed.returncode != 0 or not version:
        detail = "\n".join(
            value.strip() for value in (completed.stdout, completed.stderr) if value.strip()
        )
        raise PythonVerificationError(
            "cannot execute the digest-pinned Nagini verifier" + (f":\n{detail}" if detail else "")
        )
    return version


def _run(command: list[str], *, label: str) -> CompletedProcess[str]:
    try:
        return run(
            command,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=NAGINI_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise PythonVerificationError(
            f"{label} cannot start because Docker is unavailable"
        ) from exc
    except TimeoutExpired as exc:
        raise PythonVerificationError(
            f"{label} exceeded {NAGINI_TIMEOUT_SECONDS} seconds; proof not established"
        ) from exc
