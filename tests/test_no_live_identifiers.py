"""Regression checks preventing deployment identities in tracked text files."""

from __future__ import annotations

import ast
import hashlib
import ipaddress
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).parents[1]

EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".secrets",
        ".venv",
        ".worktrees",
        "__pycache__",
        "build",
        "coverage",
        "credentials",
        "dist",
        "generated",
        "htmlcov",
        "node_modules",
        "secrets",
        "site",
        "venv",
    }
)
EXCLUDED_SUFFIXES = frozenset(
    {
        ".bin",
        ".cap",
        ".class",
        ".dll",
        ".dylib",
        ".elf",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".o",
        ".pcap",
        ".pcapng",
        ".pdf",
        ".png",
        ".pyc",
        ".so",
        ".tar",
        ".webp",
        ".zip",
    }
)
DOTTED_TOKEN_PATTERN = re.compile(r"(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])")
MAC_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"
)
OUI_CONTEXT_PATTERN = re.compile(
    r"(?i)\boui\b[^\n]{0,40}"
    r"(?P<oui>(?<![0-9a-f:-])(?:[0-9a-f]{2}[:-]){2}[0-9a-f]{2}(?![0-9a-f:-]))"
)
HOSTNAME_PATTERN = re.compile(r"(?i)(?<![\w.-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?![\w.-])")
PLANT_IDENTIFIER_CONTEXT_PATTERN = re.compile(
    r"(?i)\bplant(?:_id)?\b[^\n0-9]{0,20}(?P<identifier>[0-9]+)"
)
DEVICE_SHAPE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z]{2}[0-9]{8}|[0-9]{5}[A-Z][0-9]{4})(?![A-Za-z0-9])"
)
AMBIGUOUS_DEVICE_CONTEXT_PATTERN = re.compile(
    r"(?ix)"
    r"\b(?:serial(?:num)?|datalog_?sn|dongle_serial|inverter_serial)\b"
    r"(?:[ \t]*[`'\"]?[ \t]*[:=][ \t]*[`'\"]?"
    r"|[ \t]*\|[ \t]*`?)"
    r"(?P<identifier>[a-z0-9]{10})\b"
)
APPROVED_AMBIGUOUS_IDENTIFIER = re.compile(
    r"(?:SYNTH|TEST|FAKE|MOCK|DEMO)[0-9A-Z]*|1234567890|([0-9])\1{9}",
    re.IGNORECASE,
)
IDENTITY_NAME_TOKENS = frozenset({"host", "ip", "serial", "mac", "dongle", "inverter"})
AUDITED_PRIVATE_IPV4_INTEGERS = frozenset(
    {
        174326024,
        174326180,
        174327265,
        174328504,
        174329007,
        174329412,
        2886729729,
    }
)
AUDITED_HOST_DIGESTS = frozenset(
    {"9c0bb928d3359b5a23821f39a1b0f39cd37cce8f45e197ad6cc8c157c7afbb05"}
)
AUDITED_PLANT_ID_DIGESTS = frozenset(
    {"7c73b217e40e18dd706368c42dbd04738fb7650d9855610970e1c65177e9679b"}
)
FIRMWARE_PART_NUMBER_PATHS = frozenset(
    {
        "docs/reference/FIRMWARE_BINARY_ANALYSIS.md",
        "docs/reference/firmware/FIRMWARE_BINARY_ANALYSIS.md",
        "scripts/extract_brand_table.py",
    }
)
FIRMWARE_PART_CONTEXT_PATTERN = re.compile(
    r"PCB revision codes|--- Part:|Engineering eval|Production, model|"
    r"validate_against\(|eTower range"
)


def _excluded_path(path: str) -> bool:
    relative_path = PurePosixPath(path)
    return (
        any(part in EXCLUDED_PARTS for part in relative_path.parts)
        or relative_path.name == ".env"
        or relative_path.name.startswith(".env.")
        or relative_path.suffix.lower() in EXCLUDED_SUFFIXES
    )


def _tracked_text_blobs() -> Iterator[tuple[str, str | None, str | None]]:
    """Read eligible tracked content from staged Git blobs, never worktree paths."""
    index = subprocess.run(
        ("git", "ls-files", "--stage", "-z"),
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    if index.returncode:
        yield "<git-index>", None, "git-index-read-failed"
        return

    for record in index.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            path = raw_path.decode("utf-8")
            mode, object_id, stage = metadata.decode("ascii").split()
        except (UnicodeDecodeError, ValueError):
            yield "<git-index>", None, "malformed-git-index-entry"
            continue

        if stage != "0":
            yield path, None, "unmerged-git-index-entry"
            continue
        if _excluded_path(path):
            continue
        if mode not in ("100644", "100755"):
            category = {
                "120000": "symlink-git-entry",
                "160000": "submodule-git-entry",
            }.get(mode, "unsupported-git-entry")
            yield path, None, category
            continue

        blob = subprocess.run(
            ("git", "cat-file", "blob", object_id),
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
        )
        if blob.returncode:
            yield path, None, "git-blob-read-failed"
            continue
        if b"\0" in blob.stdout:
            continue
        try:
            content = blob.stdout.decode("utf-8")
        except UnicodeDecodeError:
            continue
        yield path, content, None


def _has_unapproved_dotted_token(_path: str, content: str) -> bool:
    for match in DOTTED_TOKEN_PATTERN.finditer(content):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            return True
        if int(address) in AUDITED_PRIVATE_IPV4_INTEGERS:
            return True
    return False


def _has_globally_administered_identifier(
    content: str, pattern: re.Pattern[str], group: str | int = 0
) -> bool:
    return any(
        not int(match.group(group)[:2], 16) & 2 for match in pattern.finditer(content)
    )


def _fingerprint(candidate: str) -> str:
    return hashlib.sha256(candidate.lower().encode()).hexdigest()


def _has_unapproved_cloud_host(content: str) -> bool:
    return any(
        _fingerprint(match.group()) in AUDITED_HOST_DIGESTS
        for match in HOSTNAME_PATTERN.finditer(content)
    )


def _has_unapproved_plant_identifier(content: str) -> bool:
    return any(
        _fingerprint(match.group("identifier")) in AUDITED_PLANT_ID_DIGESTS
        for match in PLANT_IDENTIFIER_CONTEXT_PATTERN.finditer(content)
    )


def _has_unapproved_device_identifier(path: str, content: str) -> bool:
    for line in content.splitlines():
        if path in FIRMWARE_PART_NUMBER_PATHS and FIRMWARE_PART_CONTEXT_PATTERN.search(
            line
        ):
            continue
        if DEVICE_SHAPE_PATTERN.search(line):
            return True
        for match in AMBIGUOUS_DEVICE_CONTEXT_PATTERN.finditer(line):
            identifier = match.group("identifier")
            if not identifier.isalpha() and not APPROVED_AMBIGUOUS_IDENTIFIER.fullmatch(
                identifier
            ):
                return True
    return False


def _assignment_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    if isinstance(node, ast.AnnAssign):
        return node.target.id if isinstance(node.target, ast.Name) else None
    for target in node.targets:
        if isinstance(target, ast.Name):
            return target.id
    return None


def _identity_name(name: str) -> bool:
    return bool(IDENTITY_NAME_TOKENS.intersection(re.findall(r"[a-z]+", name.lower())))


def _has_operational_identity_default(path: str, content: str) -> bool:
    if not path.startswith("scripts/") or not path.endswith(".py"):
        return False
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False

    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        name = _assignment_name(node)
        value = node.value
        if (
            name is not None
            and value is not None
            and _identity_name(name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and value.value
        ):
            return True

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument":
            continue
        option_names = (
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        )
        if not any(_identity_name(option) for option in option_names):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "default"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
                and keyword.value.value
            ):
                return True
    return False


def _scan_repository() -> list[tuple[str, str]]:
    findings: set[tuple[str, str]] = set()
    for path, content, entry_error in _tracked_text_blobs():
        if entry_error is not None:
            findings.add((path, entry_error))
            continue
        assert content is not None
        checks = (
            ("private-or-malformed-ipv4", _has_unapproved_dotted_token(path, content)),
            ("deployment-cloud-host", _has_unapproved_cloud_host(content)),
            ("deployment-plant-id", _has_unapproved_plant_identifier(content)),
            (
                "non-synthetic-mac",
                _has_globally_administered_identifier(content, MAC_PATTERN),
            ),
            (
                "non-synthetic-oui",
                _has_globally_administered_identifier(
                    content, OUI_CONTEXT_PATTERN, "oui"
                ),
            ),
            (
                "non-synthetic-device-id",
                _has_unapproved_device_identifier(path, content),
            ),
            (
                "operational-identity-default",
                _has_operational_identity_default(path, content),
            ),
        )
        findings.update((path, category) for category, failed in checks if failed)
    return sorted(findings)


def test_tracked_text_has_no_deployment_identities() -> None:
    """Tracked text must use reserved identities or explicit runtime configuration."""
    findings = _scan_repository()
    if findings:
        summary = "\n".join(f"{path}: {category}" for path, category in findings)
        raise AssertionError(f"tracked identity audit failed:\n{summary}")


def test_identity_assignment_names_are_tokenized() -> None:
    assert _identity_name("dongle_ip")
    assert not _identity_name("spike_limit")


def test_private_ip_guard_allows_generic_rfc1918_examples() -> None:
    content = "\n".join(
        (
            "default subnet: 192.168.1.0/24",
            "generic fixture: 10.0.0.42",
            "private range base: 172.16.0.0/12",
            "unrelated private fixture: 10.100.99.1",
        )
    )

    assert not _has_unapproved_dotted_token("docs/example.md", content)


def test_private_ip_guard_detects_audited_identifier_from_integer() -> None:
    audited_address = str(ipaddress.IPv4Address(174326024))

    assert _has_unapproved_dotted_token("docs/example.md", audited_address)


def test_cloud_host_guard_detects_audited_identifier() -> None:
    audited_host = "us2." + "solarcloud" + "system.com"

    assert _has_unapproved_cloud_host(audited_host)


def test_plant_guard_detects_audited_identifier() -> None:
    audited_plant = bytes((49, 57, 49, 52, 55)).decode()

    assert _has_unapproved_plant_identifier(f"plant {audited_plant}")
