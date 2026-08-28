"""Create local, redacted diagnostic bundles for skillsaw bug reports."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import platform
import re
import secrets
import select
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ..config import find_config
from ..paths import contained_resolve, safe_exists, safe_is_dir, safe_is_file, safe_resolve
from ..rules.builtin.secret_detection import STRUCTURED_SECRET_PATTERNS
from ._config import _get_version

_ISSUE_URL = "https://github.com/stbenjam/skillsaw/issues/new"
_FEEDBACK_EMAIL = "stephen@bitbin.de"
_GPG_KEY_URL = "https://github.com/stbenjam.gpg"
_BUNDLE_SCHEMA_VERSION = 1
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?im)^(\s*[\"']?(?:[A-Za-z_][A-Za-z0-9_.-]*)?"
    r"(?:api[_-]?key|token|secret|password|passphrase|credential)"
    r"[A-Za-z0-9_.-]*[\"']?\s*[:=]\s*)(.+)$"
)
_AUTHORIZATION_HEADER = re.compile(r"(?im)^(\s*(?:proxy-)?authorization\s*[:=]\s*)(.+)$")
_BEARER_TOKEN = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/-]{12,}")
_URL_USERINFO = re.compile(r"(?://)([^/\s:@]+(?::[^@/\s]+)?@)")
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    re.DOTALL,
)
_BLOCK_SCALAR_CREDENTIAL = re.compile(
    r"(?im)^(\s*[\"']?(?:[A-Za-z_][A-Za-z0-9_.-]*)?"
    r"(?:api[_-]?key|token|secret|password|passphrase|credential)[A-Za-z0-9_.-]*[\"']?"
    r"\s*:\s*[>|][^\n]*\n)(?:^[ \t]+.*(?:\n|$))*"
)


def _redact_text(text: str) -> tuple[str, int]:
    """Redact credential-shaped text without retaining the original value."""
    redactions = 0

    def replace_with_marker(match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        return "[REDACTED]"

    text, _count = _PEM_PRIVATE_KEY.subn(replace_with_marker, text)
    text, count = _BLOCK_SCALAR_CREDENTIAL.subn(r"\1[REDACTED]\n", text)
    redactions += count
    for pattern, _description in STRUCTURED_SECRET_PATTERNS:
        text = pattern.sub(replace_with_marker, text)
    text, count = _CREDENTIAL_ASSIGNMENT.subn(r"\1[REDACTED]", text)
    redactions += count
    text, count = _AUTHORIZATION_HEADER.subn(r"\1[REDACTED]", text)
    redactions += count
    text, count = _BEARER_TOKEN.subn(r"\1[REDACTED]", text)
    redactions += count
    text, count = _URL_USERINFO.subn("//[REDACTED]@", text)
    redactions += count
    return text, redactions


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle_id(created_at: datetime) -> str:
    return f"skillsaw-feedback-{created_at.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def _archive_path(args, root: Path, bundle_id: str) -> Path | None:
    if args.output is not None:
        output = args.output
        if output.suffix.lower() != ".zip":
            output = output.with_suffix(".zip")
        return safe_resolve(output)
    return root / ".skillsaw-feedback" / f"{bundle_id}.zip"


def _config_path(args, root: Path) -> Path | None:
    if args.config is not None:
        return safe_resolve(args.config)
    return find_config(root)


def _included_file(root: Path, raw_path: str) -> tuple[Path, Path]:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = contained_resolve(candidate, root)
    if resolved is None:
        raise ValueError(f"--include must name a file inside the repository: {raw_path}")
    if not safe_is_file(resolved):
        raise ValueError(f"--include must name a file: {raw_path}")
    relative = resolved.relative_to(root)
    return resolved, relative


def _run_diagnostic_lint(
    root: Path, config_path: Path | None, *, with_extensions: bool
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "skillsaw",
        "lint",
        "--format",
        "json",
        "--verbose",
        "--no-baseline",
    ]
    if config_path is not None:
        command.extend(["--config", str(config_path)])
    if not with_extensions:
        command.extend(["--no-custom-rules", "--no-plugins"])
    command.append(".")
    try:
        stdout, stderr, return_code = _run_lint_process(command, root)
        return {
            "command": ["skillsaw", "lint", "--format", "json", "--verbose", "--no-baseline"],
            "exit_code": return_code,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return {
            "command": ["skillsaw", "lint", "--format", "json", "--verbose", "--no-baseline"],
            "exit_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
        }


def _run_lint_process(command: list[str], root: Path) -> tuple[str, str, int]:
    """Run lint, mirroring its interactive progress line into this terminal."""
    if not sys.stderr.isatty() or os.name == "nt":
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        return completed.stdout, completed.stderr, completed.returncode

    import pty

    master, slave = pty.openpty()
    captured_stderr = bytearray()
    try:
        with tempfile.TemporaryFile(mode="w+b") as stdout_file:
            process = subprocess.Popen(command, cwd=root, stdout=stdout_file, stderr=slave)
            os.close(slave)
            slave = -1
            deadline = time.monotonic() + 120
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    stdout_file.seek(0)
                    raise subprocess.TimeoutExpired(
                        command, 120, output=stdout_file.read(), stderr=bytes(captured_stderr)
                    )
                readable, _unused, _errors = select.select([master], [], [], min(0.1, remaining))
                if readable:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        # Linux PTYs signal EOF with EIO after the child closes its slave.
                        if error.errno != errno.EIO:
                            raise
                        break
                    if chunk:
                        captured_stderr.extend(chunk)
                        sys.stderr.buffer.write(chunk)
                        sys.stderr.buffer.flush()
                    elif process.poll() is not None:
                        break
                elif process.poll() is not None:
                    break
            return_code = process.wait(timeout=max(0, deadline - time.monotonic()))
            stdout_file.seek(0)
            stdout = stdout_file.read().decode("utf-8", "replace")
    finally:
        if slave >= 0:
            os.close(slave)
        os.close(master)
    return stdout, captured_stderr.decode("utf-8", "replace"), return_code


def _replace_local_paths(text: str, root: Path, config_path: Path | None) -> str:
    """Keep machine-specific local paths out of text reports."""
    if root != Path(root.anchor):
        text = text.replace(str(root), "<repository>")
    if config_path is not None:
        text = text.replace(str(config_path), "<config>")
    return text


def _issue_url(bundle_name: str, bundle_sha256: str, message: str) -> str:
    body = (
        "### Diagnostic bundle\n\n"
        "Created with `skillsaw feedback`; repository files are omitted unless explicitly "
        "included with `--include` or `--config`. Please attach the generated ZIP to this issue.\n\n"
        f"- Bundle: `{bundle_name}`\n"
        f"- SHA-256: `{bundle_sha256}`\n"
    )
    if message:
        body += f"\n### Reporter note\n\n{message}\n"
    return f"{_ISSUE_URL}?{urlencode({'template': 'bug_report.yml', 'body': body})}"


def _run_feedback(args) -> None:
    if not safe_is_dir(args.path):
        print(f"Error: Path is not a directory: {args.path}", file=sys.stderr)
        sys.exit(1)

    root = safe_resolve(args.path)
    if root is None:
        print(f"Error: Path could not be resolved: {args.path}", file=sys.stderr)
        sys.exit(1)
    config_path = _config_path(args, root)
    if args.config is not None and config_path is None:
        print(f"Error: Config file could not be resolved: {args.config}", file=sys.stderr)
        sys.exit(1)
    if config_path is not None and not safe_is_file(config_path):
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    created_at = datetime.now(timezone.utc)
    bundle_id = _bundle_id(created_at)
    output_path = _archive_path(args, root, bundle_id)
    if output_path is None:
        print(f"Error: Bundle path could not be resolved: {args.output}", file=sys.stderr)
        sys.exit(1)
    if safe_exists(output_path):
        print(f"Error: Bundle already exists: {output_path}", file=sys.stderr)
        sys.exit(1)

    try:
        selected_files = [_included_file(root, raw_path) for raw_path in args.include]
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    lint = _run_diagnostic_lint(root, config_path, with_extensions=args.with_extensions)
    artifact_texts: dict[str, str] = {}
    redactions = 0
    for name, raw_text in (
        ("lint-report.json", lint["stdout"]),
        ("lint-stderr.txt", lint["stderr"]),
    ):
        cleaned = _replace_local_paths(raw_text, root, config_path)
        artifact_texts[name], count = _redact_text(cleaned)
        redactions += count

    config_included = args.config is not None
    if config_included:
        assert config_path is not None
        try:
            raw_config = config_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            print(f"Error: Could not read config file: {config_path}", file=sys.stderr)
            sys.exit(1)
        artifact_texts["skillsaw-config.yaml"], count = _redact_text(raw_config)
        redactions += count

    included_names = []
    for _file_path, relative in selected_files:
        try:
            file_path, relative = _included_file(root, str(relative))
            raw_content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            print(f"Error: Could not read --include file: {relative}", file=sys.stderr)
            sys.exit(1)
        archive_name = f"included/{relative.as_posix()}"
        artifact_texts[archive_name], count = _redact_text(raw_content)
        redactions += count
        included_names.append(relative.as_posix())

    message, count = _redact_text(args.message)
    redactions += count
    environment = {
        "bundle_schema_version": _BUNDLE_SCHEMA_VERSION,
        "created_at": created_at.isoformat(),
        "skillsaw_version": _get_version(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "lint_exit_code": lint["exit_code"],
        "lint_timed_out": lint["timed_out"],
        "lint_extensions_enabled": args.with_extensions,
        "config_included": config_included,
        "included_files": included_names,
        "message": message,
    }
    artifact_texts["environment.json"] = json.dumps(environment, indent=2, sort_keys=True) + "\n"

    artifact_bytes = {name: text.encode("utf-8") for name, text in artifact_texts.items()}
    manifest = {
        "bundle_schema_version": _BUNDLE_SCHEMA_VERSION,
        "redactions": redactions,
        "files": {
            name: {"sha256": _sha256(data), "size_bytes": len(data)}
            for name, data in sorted(artifact_bytes.items())
        },
    }
    artifact_bytes["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    temporary_path = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(f".{output_path.name}.{secrets.token_hex(4)}.tmp")
        descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as archive_file:
            with zipfile.ZipFile(archive_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in sorted(artifact_bytes.items()):
                    archive.writestr(f"{bundle_id}/{name}", data)
        os.link(temporary_path, output_path)
        temporary_path.unlink()
    except (OSError, zipfile.BadZipFile) as error:
        print(f"Error: Could not write diagnostic bundle: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    bundle_sha256 = _sha256(output_path.read_bytes())
    issue_url = _issue_url(output_path.name, bundle_sha256, message)
    result = {
        "bundle": str(output_path),
        "archive_directory": bundle_id,
        "sha256": bundle_sha256,
        "issue_url": issue_url,
        "email": {"to": _FEEDBACK_EMAIL, "gpg_key": _GPG_KEY_URL},
        "included_files": included_names,
        "redactions": redactions,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("Feedback bundle created")
        print(f"  File:     {output_path}")
        print(f"  Extracts: {bundle_id}/")
        print(f"  SHA-256:  {bundle_sha256}")
        print(f"  Redacted: {redactions} value(s)")
        print()
        print("Review before sharing")
        print("  Open the ZIP and confirm you are comfortable sharing every file in it.")
        print("  skillsaw makes a best effort to redact credential-shaped values, but")
        print("  redaction is not guaranteed to catch every secret or sensitive detail.")
        print()
        print("Share the reviewed bundle")
        print("  GitHub issue:")
        print(f"    {issue_url}")
        print("  Private email:")
        print(f"    Attach it to {_FEEDBACK_EMAIL}")
        print(f"    Optional GPG key: {_GPG_KEY_URL}")
    sys.exit(0)
