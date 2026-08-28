"""Create local, redacted diagnostic bundles for skillsaw bug reports."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import secrets
import subprocess
import sys
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
_BUNDLE_SCHEMA_VERSION = 1
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?im)^(\s*[\"']?[A-Za-z_][A-Za-z0-9_.-]*"
    r"(?:api[_-]?key|token|secret|password|passphrase|credential)"
    r"[A-Za-z0-9_.-]*[\"']?\s*[:=]\s*)(.+)$"
)
_AUTHORIZATION_HEADER = re.compile(r"(?im)^(\s*(?:proxy-)?authorization\s*[:=]\s*)(.+)$")
_BEARER_TOKEN = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/-]{12,}")
_URL_USERINFO = re.compile(r"(?://)([^/\s:@]+(?::[^@/\s]+)?@)")


def _redact_text(text: str) -> tuple[str, int]:
    """Redact credential-shaped text without retaining the original value."""
    redactions = 0

    def replace_with_marker(match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        return "[REDACTED]"

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


def _archive_path(args, root: Path, created_at: datetime) -> Path | None:
    if args.output is not None:
        output = args.output
        if output.suffix.lower() != ".zip":
            output = output.with_suffix(".zip")
        return safe_resolve(output)
    stamp = created_at.strftime("%Y%m%dT%H%M%SZ")
    return root / ".skillsaw-feedback" / f"feedback-{stamp}-{secrets.token_hex(4)}.zip"


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
        "--no-progress",
    ]
    if config_path is not None:
        command.extend(["--config", str(config_path)])
    if not with_extensions:
        command.extend(["--no-custom-rules", "--no-plugins"])
    command.append(".")
    try:
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
        return {
            "command": ["skillsaw", "lint", "--format", "json", "--verbose", "--no-progress"],
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
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
            "command": ["skillsaw", "lint", "--format", "json", "--verbose", "--no-progress"],
            "exit_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
        }


def _replace_local_paths(text: str, root: Path, config_path: Path | None) -> str:
    """Keep machine-specific local paths out of text reports."""
    text = text.replace(str(root), "<repository>")
    if config_path is not None:
        text = text.replace(str(config_path), "<config>")
    return text


def _issue_url(bundle_name: str, bundle_sha256: str, message: str) -> str:
    body = (
        "### Diagnostic bundle\n\n"
        "Created with `skillsaw feedback`; repository files are omitted unless explicitly "
        "included with `--include`. Please attach the generated ZIP to this issue.\n\n"
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
    output_path = _archive_path(args, root, created_at)
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

    config_included = config_path is not None
    if config_path is not None:
        raw_config = config_path.read_text(encoding="utf-8", errors="replace")
        artifact_texts["skillsaw-config.yaml"], count = _redact_text(raw_config)
        redactions += count

    included_names = []
    for file_path, relative in selected_files:
        try:
            raw_content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"Error: --include only supports UTF-8 text files: {relative}", file=sys.stderr)
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

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(f".{output_path.name}.{secrets.token_hex(4)}.tmp")
        with zipfile.ZipFile(temporary_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(artifact_bytes.items()):
                archive.writestr(name, data)
        temporary_path.replace(output_path)
    except (OSError, zipfile.BadZipFile) as error:
        print(f"Error: Could not write diagnostic bundle: {error}", file=sys.stderr)
        sys.exit(1)

    bundle_sha256 = _sha256(output_path.read_bytes())
    issue_url = _issue_url(output_path.name, bundle_sha256, message)
    result = {
        "bundle": str(output_path),
        "sha256": bundle_sha256,
        "issue_url": issue_url,
        "included_files": included_names,
        "redactions": redactions,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"Created diagnostic bundle: {output_path}")
        print(f"SHA-256: {bundle_sha256}")
        print(f"Redactions applied: {redactions}")
        print("Review the ZIP, then attach it to a bug report:")
        print(issue_url)
    sys.exit(0)
