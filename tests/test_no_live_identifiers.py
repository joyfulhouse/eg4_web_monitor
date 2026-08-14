"""Regression checks preventing deployment identities in tracked text files."""

from __future__ import annotations

import ast
import hashlib
import ipaddress
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

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
OUI_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){2}[0-9a-f]{2}(?![0-9a-f:-])"
)
DEVICE_CONTEXT_PATTERN = re.compile(
    r"(?ix)"
    r"\b(?:18kpv|flexboss21|gridboss|grid_boss|battery_bank)"
    r"(?:[\s_:()\-]|[`'\"])+"
    r"(?P<identifier>[a-z0-9]{10})\b"
)
APPROVED_CONTEXT_IDENTIFIER = re.compile(
    r"(?:SYNTH|TEST|FAKE|MOCK|DEMO)[0-9A-Z]*|1234567890|FlexBOSS18",
    re.IGNORECASE,
)
IDENTITY_WORDS = ("host", "ip", "serial", "mac", "dongle", "inverter")

# SHA-256 fingerprints let the regression guard reject the audited deployment
# values without retaining those values in source, diagnostics, or test output.
AUDITED_FINGERPRINTS = {
    "device-id": frozenset(
        {
            "1e4ff575e946e60bebc60e90f22f691ae40c39b005e4a9c17070c47bd8af62d4",
            "36ecf9133cf3bb7963d53f30ff300c9f376c7ba12eefa341114563518bea8ec5",
            "434b6cb54f29a029ac78060f6d5c6bbec9b46c17127a1514c01a4a9c1fa49331",
            "5b0f86182b3a1c30f17715d6a58913da4e9c3d17677637c873d0e08f395a53a8",
            "62d0332c5c362882484d48b19cbc98695b57a6c75b8dd5700175488216fd856d",
            "702d5c518487bbc3f73a871e2abc2b04b82fc3988eba590b1b295df0e7f59f9e",
            "7619ee8cea49187f309616e30ecf54be072259b43760f1f550a644945d5572f2",
            "87d9c507b69c8d2ebf9d49e497c3f857d296e9cc341287f0f305b67dfb2c21ec",
            "90442bb3b709fffb1e5ed9faa09676e75900ca1665a9bc93ed65869179897139",
            "92b778c32c63ceeb6a842881b954595d9514829c820ed96efc6455d7480aabf0",
            "965f69baefb60286c60262b40dcf40717a2227eef5db00c9b717d5de24453511",
            "ce3a598687c8d2e5aa6bedad20e059b4a78cca0adad7e563b07998d5cd226b8c",
            "d2d02ea74de2c9fab1d802db969c18d409a8663a9697977bb1c98ccdd9de4372",
            "eb8dd50850c7b3ef3783bca21918688873c8a09e1f7dbb40db13c30d2869011b",
        }
    ),
    "private-ipv4": frozenset(
        {
            "2a39f1eedcd9f986327b5e4da842426f4f05b8f16f0ef385639dbec0db70eaae",
            "439b4a00083e633e5777ebf9b72d1f17b2863a6e0b4808e08aadfd202ac7064e",
            "48e844f1045944faf0d2480a5ab6c96eb56ae8bdc05f72cfb886eed6534e509e",
            "5b4e4c93c69254676aaa53aa9cc542efa38c27affe6c8c9be5d4a76986f4b4ee",
            "725b4c8929840ff6c88be48f3ea31e88d7b44485de136c65a1b90965874d17d5",
            "7eaec80bc86ebffdd27e3b783714279190b826f0669f8e2bdb59026193c71939",
            "a58ccf7228e2d085851c88e0fbb959a3591245533a4faf103e5902fcf84d9d60",
            "d13975c9b6ed279369067b4753fe0b9d64e94452413001f72d5b3e6c41124309",
            "d7da75db715e9ec489582517601f380b201872bb0a281a5c6b04bca3ddca5cad",
            "f9863b6fa829fa6e80ffce0a30779b91c9affd96c0ee47f303c2c000b84a7b24",
        }
    ),
    "mac": frozenset(
        {
            "100dc7699927df43b804098539988a6830ef362353bc3c01206dc3ff4324d593",
            "278645e7b55885f924ba59642a7df6167b9a8409f330cb65ecb1c1a3ab49b4f5",
            "806e18d1f1a9d7e99501dbe0fb4434f1dea1de6d0d35c53c7a241a6109201bb2",
        }
    ),
    "oui": frozenset(
        {
            "0ead08545c6a243f9628323fce66e7ab79a44f8f7a7dde17ef65ad31a5c367f7",
            "1b7ae2d116e01e63ccc87272cce878e032ebaf2c503474cff5fa09930b99aeb4",
            "e7ebcf5379a29dec5361782d00922dd83ea0468b0d95b1b3573dca65e85e1d31",
        }
    ),
}


def _tracked_text_files() -> Iterator[tuple[str, str]]:
    """Yield decoded tracked text without traversing untracked or secret stores."""
    result = subprocess.run(
        ("git", "ls-files", "-z"),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative_path = Path(raw_path.decode("utf-8"))
        if (
            any(part in EXCLUDED_PARTS for part in relative_path.parts)
            or relative_path.name == ".env"
            or relative_path.name.startswith(".env.")
            or relative_path.suffix.lower() in EXCLUDED_SUFFIXES
        ):
            continue

        data = (REPOSITORY_ROOT / relative_path).read_bytes()
        if b"\0" in data:
            continue
        try:
            yield relative_path.as_posix(), data.decode("utf-8")
        except UnicodeDecodeError:
            continue


def _has_unapproved_dotted_token(content: str) -> bool:
    for match in DOTTED_TOKEN_PATTERN.finditer(content):
        try:
            ipaddress.ip_address(match.group())
        except ValueError:
            return True
        if _fingerprint(match.group()) in AUDITED_FINGERPRINTS["private-ipv4"]:
            return True
    return False


def _contains_audited_value(
    content: str, pattern: re.Pattern[str], category: str
) -> bool:
    fingerprints = AUDITED_FINGERPRINTS[category]
    return any(
        _fingerprint(match.group()) in fingerprints
        for match in pattern.finditer(content)
    )


def _has_unapproved_device_identifier(content: str) -> bool:
    for match in DEVICE_CONTEXT_PATTERN.finditer(content):
        candidate = match.group("identifier")
        if _fingerprint(candidate) in AUDITED_FINGERPRINTS["device-id"]:
            return True
        if any(character.isdigit() for character in candidate):
            if not APPROVED_CONTEXT_IDENTIFIER.fullmatch(candidate):
                return True
    return False


def _fingerprint(candidate: str) -> str:
    return hashlib.sha256(candidate.lower().encode("utf-8")).hexdigest()


def _assignment_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    if isinstance(node, ast.AnnAssign):
        return node.target.id if isinstance(node.target, ast.Name) else None
    for target in node.targets:
        if isinstance(target, ast.Name):
            return target.id
    return None


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
            and any(word in name.lower() for word in IDENTITY_WORDS)
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
        option_names = [
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        ]
        if not any(
            word in option.lower() for option in option_names for word in IDENTITY_WORDS
        ):
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
    for path, content in _tracked_text_files():
        checks = (
            ("private-or-malformed-ipv4", _has_unapproved_dotted_token(content)),
            ("non-synthetic-mac", _contains_audited_value(content, MAC_PATTERN, "mac")),
            ("non-synthetic-oui", _contains_audited_value(content, OUI_PATTERN, "oui")),
            ("non-synthetic-device-id", _has_unapproved_device_identifier(content)),
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
