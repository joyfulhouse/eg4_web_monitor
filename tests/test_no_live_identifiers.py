"""Regression checks preventing deployment identities in tracked text files."""

from __future__ import annotations

import ast
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest

REPOSITORY_ROOT = Path(__file__).parents[1]
AUDIT_VECTOR_PATH = REPOSITORY_ROOT / ".identifier-audit-vectors.json"

EXCLUDED_PATH_PREFIXES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".secrets",
        ".venv",
        ".worktrees",
        "__pycache__",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
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
INTEGER_TOKEN_PATTERN = re.compile(r"(?<![\w.])[0-9]{8,10}(?![\w.])")
MAC_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"
)
HOSTNAME_PATTERN = re.compile(r"(?i)(?<![\w.-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?![\w.-])")
PLANT_IDENTIFIER_CONTEXT_PATTERN = re.compile(
    r"(?i)plant[_ ]?id[^\n0-9]{0,20}(?P<identifier>[0-9]+)"
)
PLANT_PROSE_CONTEXT_PATTERN = re.compile(
    r"(?i)\bplant(?![a-z])[^\n0-9]{0,20}(?P<identifier>[0-9]+)"
)
PLANT_JSON_OBJECT_PATTERN = re.compile(
    r'(?is)\{(?=[^{}]{0,500}"(?:plant|station)[^"]*"\s*:)[^{}]{0,500}'
    r'"id"\s*:\s*(?P<identifier>[0-9]+)'
)
DEVICE_SHAPE_PATTERN = re.compile(r"(?i)(?<![a-z0-9])[a-z0-9]{10}(?![a-z0-9])")
IDENTITY_NAME_TOKENS = frozenset({"host", "ip", "serial", "mac", "dongle", "inverter"})
LOCATION_ADDRESS_PATTERN = re.compile(
    r"(?i)(?<![a-z0-9])(?P<address>[0-9]{1,6}(?:[ +_][a-z]+){2,8})(?![a-z0-9])"
)
LOCATION_COORDINATE_PATTERN = re.compile(
    r"(?<![\w.])(?P<coordinate>-?[0-9]{1,3}\.[0-9]{4,8})(?![\w.])"
)
AUDITED_PRIVATE_IPV4_DIGESTS = frozenset(
    {
        "439b4a00083e633e5777ebf9b72d1f17b2863a6e0b4808e08aadfd202ac7064e",
        "48e844f1045944faf0d2480a5ab6c96eb56ae8bdc05f72cfb886eed6534e509e",
        "5b4e4c93c69254676aaa53aa9cc542efa38c27affe6c8c9be5d4a76986f4b4ee",
        "7eaec80bc86ebffdd27e3b783714279190b826f0669f8e2bdb59026193c71939",
        "a58ccf7228e2d085851c88e0fbb959a3591245533a4faf103e5902fcf84d9d60",
        "d13975c9b6ed279369067b4753fe0b9d64e94452413001f72d5b3e6c41124309",
    }
)
AUDITED_PRIVATE_IPV4_INTEGER_DIGESTS = frozenset(
    {
        "22b54bd6279733e32d8c54598f41024fa0622ccf0aacdb947d61894e461b2695",
        "292f1800c99e23c1eee0ab7c7f20728929b351df559e33e7f2e70a966a5e93d1",
        "4bf1623f0cff64bc89fb8cc7831edaa108d5d5b5568ce66515e598af2a8fe8d9",
        "4d99185f9aeb77c97a985a18a26143944aff8a04d78375952cc6c0023b241356",
        "540069d390616d9cd3378aad058c6274738169664adf4349c8d6feeda620780b",
        "7f3b26fa4ac19fbdd514cfda17db89961e206767c70667fe09fe2de2ed0bc6b5",
        "87b91ba1df4c2bb7c8549fd3d8c5eb18c8346db76c43af99a7f4c78a00f2b30a",
        "890afa14242fa68f9a45b0847b4be5c747613a5f8b6bae936917a35e84694949",
        "8e722e7e811537f571c1098aa7a27e2e8e21ea46ab19f9c3425fc21e8b50599a",
        "9270bb10e790cf84ed07f6b721651324003db1163c1019469e1b9f4d21e42618",
        "ba38c9ab6106d8850587504bab1829ea6d6edb875eaab536a12bfa6e94873775",
        "c1e4594b035720a6b76823e387a15aff7abf962818871842bd08d8aab7f4a00d",
    }
)
# Generic EG4 vendor hosts are intentionally out of scope; only deployment-specific
# hosts belong in this registry.
AUDITED_HOST_DIGESTS: frozenset[str] = frozenset()
AUDITED_PLANT_ID_DIGESTS = frozenset(
    {"7c73b217e40e18dd706368c42dbd04738fb7650d9855610970e1c65177e9679b"}
)
AUDITED_DEVICE_IDENTIFIER_DIGESTS = frozenset(
    {
        "06ac878b82ebd54019b33ae1855d5d1433dbf1f4aaa0a49fb76f77c1b86999b8",
        "0d50411460c711e083cca616ec877decf926958012244948d3e4fb86fc0f8fe0",
        "23ff893684527c7dd50552ae9a6ff83b44e92c96c9b913c0d5acb585a6b7bef6",
        "645558e9c422de25cfa66aee937f7cc83b27d954903e3492adbf0754fea45053",
        "702d5c518487bbc3f73a871e2abc2b04b82fc3988eba590b1b295df0e7f59f9e",
        "87d9c507b69c8d2ebf9d49e497c3f857d296e9cc341287f0f305b67dfb2c21ec",
        "92b778c32c63ceeb6a842881b954595d9514829c820ed96efc6455d7480aabf0",
        "b312f33941101b68c0f5f1a2a50bb9c2be6b989f07044777c8ecc23a2378fbf2",
        "eb8dd50850c7b3ef3783bca21918688873c8a09e1f7dbb40db13c30d2869011b",
    }
)
AUDITED_LOCATION_DIGESTS = frozenset(
    {
        "22efccf7c50867aa71949cb10e460dfafa6ef0ca0d541f7358fbd25f9b3736ba",
        "2a8a7f989a302bb594a4b7fecf20128743aaba5c7aaf411100fcece1430e30ac",
        "c964c8e2e4dc0f9eb903744a2259fc5840d1d44557c03265571ced34dcbed858",
        "f85bba23ed2ac9317a8457f45999dbf1e271ddc5920b8e75d9e56830bff7879e",
    }
)
AUDITED_MAC_DIGESTS = frozenset(
    {
        "100dc7699927df43b804098539988a6830ef362353bc3c01206dc3ff4324d593",
        "278645e7b55885f924ba59642a7df6167b9a8409f330cb65ecb1c1a3ab49b4f5",
        "806e18d1f1a9d7e99501dbe0fb4434f1dea1de6d0d35c53c7a241a6109201bb2",
    }
)


def _excluded_path(path: str) -> bool:
    relative_path = PurePosixPath(path)
    normalized = relative_path.as_posix()
    return (
        any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in EXCLUDED_PATH_PREFIXES
        )
        or relative_path.name == ".env"
        or relative_path.name.startswith(".env.")
        or relative_path.suffix.lower() in EXCLUDED_SUFFIXES
    )


def _tracked_text_blobs() -> Iterator[tuple[str, str | None, str | None]]:
    """Read eligible staged content from index blobs."""
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
        raw_content = blob.stdout
        if b"\0" in raw_content:
            continue
        try:
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        yield path, content, None


def _has_unapproved_dotted_token(_path: str, content: str) -> bool:
    for match in DOTTED_TOKEN_PATTERN.finditer(content):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            return True
        if _fingerprint(str(address)) in AUDITED_PRIVATE_IPV4_DIGESTS:
            return True
    return False


def _has_unapproved_integer_ip(content: str) -> bool:
    return any(
        _fingerprint(match.group()) in AUDITED_PRIVATE_IPV4_INTEGER_DIGESTS
        for match in INTEGER_TOKEN_PATTERN.finditer(content)
    )


def _has_audited_mac(content: str) -> bool:
    return any(
        _fingerprint(match.group()) in AUDITED_MAC_DIGESTS
        for match in MAC_PATTERN.finditer(content)
    )


def _fingerprint(candidate: str) -> str:
    return hashlib.sha256(candidate.lower().encode()).hexdigest()


def _load_audit_vectors() -> dict[str, list[str]]:
    if not AUDIT_VECTOR_PATH.exists():
        pytest.skip("local identifier audit vector is not installed")
    return json.loads(AUDIT_VECTOR_PATH.read_text())


def _has_unapproved_cloud_host(content: str) -> bool:
    return any(
        _fingerprint(match.group()) in AUDITED_HOST_DIGESTS
        for match in HOSTNAME_PATTERN.finditer(content)
    )


def _has_unapproved_plant_identifier(content: str) -> bool:
    return any(
        _fingerprint(match.group("identifier")) in AUDITED_PLANT_ID_DIGESTS
        for pattern in (
            PLANT_IDENTIFIER_CONTEXT_PATTERN,
            PLANT_PROSE_CONTEXT_PATTERN,
            PLANT_JSON_OBJECT_PATTERN,
        )
        for match in pattern.finditer(content)
    )


def _location_fingerprint(candidate: str) -> str:
    normalized = re.sub(r"[^a-z0-9.-]", "", candidate.lower())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _location_candidates(content: str) -> Iterator[str]:
    for match in LOCATION_COORDINATE_PATTERN.finditer(content):
        yield match.group("coordinate")
    for match in LOCATION_ADDRESS_PATTERN.finditer(content):
        address = match.group("address")
        yield address
        parts = re.split(r"[ +_]", address)
        for length in range(3, len(parts)):
            yield " ".join(parts[:length])


def _has_unapproved_location(content: str) -> bool:
    return any(
        _location_fingerprint(candidate) in AUDITED_LOCATION_DIGESTS
        for candidate in _location_candidates(content)
    )


def _has_unapproved_device_identifier(path: str, content: str) -> bool:
    del path
    return any(
        _fingerprint(match.group()) in AUDITED_DEVICE_IDENTIFIER_DIGESTS
        for match in DEVICE_SHAPE_PATTERN.finditer(content)
    )


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
    is_script = path.startswith("scripts/") and path.endswith(".py")
    is_config_flow = (
        path.startswith("custom_components/")
        and "/_config_flow/" in path
        and path.endswith(".py")
    )
    if not is_script and not is_config_flow:
        return False
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False

    if is_script:
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

    if is_config_flow:
        rfc1918_networks = tuple(
            ipaddress.ip_network(network)
            for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            try:
                network = ipaddress.ip_network(node.value, strict=False)
            except ValueError:
                continue
            if not any(network.subnet_of(private) for private in rfc1918_networks):
                return True

    if not is_script:
        return False
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
            ("encoded-private-ipv4", _has_unapproved_integer_ip(content)),
            ("deployment-cloud-host", _has_unapproved_cloud_host(content)),
            ("deployment-plant-id", _has_unapproved_plant_identifier(content)),
            ("deployment-location", _has_unapproved_location(content)),
            ("deployment-mac", _has_audited_mac(content)),
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


def test_audited_values_are_stored_only_as_sha256_digests() -> None:
    registries = (
        AUDITED_PRIVATE_IPV4_DIGESTS,
        AUDITED_PRIVATE_IPV4_INTEGER_DIGESTS,
        AUDITED_HOST_DIGESTS,
        AUDITED_PLANT_ID_DIGESTS,
        AUDITED_DEVICE_IDENTIFIER_DIGESTS,
        AUDITED_LOCATION_DIGESTS,
        AUDITED_MAC_DIGESTS,
    )
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", digest)
        for registry in registries
        for digest in registry
    )


def test_committed_digests_match_local_audit_vectors() -> None:
    vectors = _load_audit_vectors()
    private_addresses = [
        ipaddress.IPv4Address(value) for value in vectors["private_ipv4"]
    ]
    expected_integer_tokens = {
        token
        for address in private_addresses
        for token in (
            str(int(address)),
            str(int.from_bytes(address.packed, "little")),
        )
    }

    assert AUDITED_PRIVATE_IPV4_DIGESTS == frozenset(
        _fingerprint(str(address)) for address in private_addresses
    )
    assert AUDITED_PRIVATE_IPV4_INTEGER_DIGESTS == frozenset(
        _fingerprint(token) for token in expected_integer_tokens
    )
    assert AUDITED_HOST_DIGESTS == frozenset(
        _fingerprint(value) for value in vectors["deployment_hosts"]
    )
    assert AUDITED_PLANT_ID_DIGESTS == frozenset(
        _fingerprint(value) for value in vectors["plant_ids"]
    )
    assert AUDITED_DEVICE_IDENTIFIER_DIGESTS == frozenset(
        _fingerprint(value) for value in vectors["device_identifiers"]
    )
    assert AUDITED_LOCATION_DIGESTS == frozenset(
        _location_fingerprint(value) for value in vectors["locations"]
    )
    assert AUDITED_MAC_DIGESTS == frozenset(
        _fingerprint(value) for value in vectors["full_macs"]
    )


def test_private_ip_guard_allows_generic_rfc1918_examples() -> None:
    content = "\n".join(
        (
            f"default subnet: {ipaddress.IPv4Address(3232235776)}/24",
            f"generic fixture: {ipaddress.IPv4Address(167772202)}",
            f"private range base: {ipaddress.IPv4Address(2886729728)}/12",
            f"unrelated private fixture: {ipaddress.IPv4Address(174391041)}",
            "generic gateway: 172.16.0.1",
        )
    )

    assert not _has_unapproved_dotted_token("docs/example.md", content)


def test_private_ip_guard_detects_audited_identifier_by_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic_address = "198.51.100.42"
    monkeypatch.setattr(
        sys.modules[__name__],
        "AUDITED_PRIVATE_IPV4_DIGESTS",
        frozenset({_fingerprint(synthetic_address)}),
    )

    assert _has_unapproved_dotted_token("docs/example.md", synthetic_address)


def test_private_ip_guard_detects_bare_integer_in_both_byte_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic_address = ipaddress.IPv4Address("198.51.100.42")
    integer_tokens = {
        str(int(synthetic_address)),
        str(int.from_bytes(synthetic_address.packed, "little")),
    }
    monkeypatch.setattr(
        sys.modules[__name__],
        "AUDITED_PRIVATE_IPV4_INTEGER_DIGESTS",
        frozenset(_fingerprint(token) for token in integer_tokens),
    )

    assert all(_has_unapproved_integer_ip(token) for token in integer_tokens)


def test_cloud_host_guard_detects_audited_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic_host = "private-cloud.example.test"
    monkeypatch.setattr(
        sys.modules[__name__],
        "AUDITED_HOST_DIGESTS",
        frozenset({_fingerprint(synthetic_host)}),
    )

    assert _has_unapproved_cloud_host(synthetic_host)


def test_vendor_cloud_hosts_are_intentionally_out_of_scope() -> None:
    assert not _has_unapproved_cloud_host(
        "us2.solarcloudsystem.com res.solarcloudsystem.com"
    )


@pytest.mark.parametrize("label", ("plantId", "targetPlantId", "plant_id", "plant"))
def test_plant_guard_detects_identifier_contexts(
    monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    synthetic_plant = "987654321"
    monkeypatch.setattr(
        sys.modules[__name__],
        "AUDITED_PLANT_ID_DIGESTS",
        frozenset({_fingerprint(synthetic_plant)}),
    )

    assert _has_unapproved_plant_identifier(f"{label}={synthetic_plant}")


def test_plant_guard_detects_json_id_in_plant_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic_plant = "987654321"
    monkeypatch.setattr(
        sys.modules[__name__],
        "AUDITED_PLANT_ID_DIGESTS",
        frozenset({_fingerprint(synthetic_plant)}),
    )

    assert _has_unapproved_plant_identifier(
        f'{{"id": {synthetic_plant}, "plantName": "Synthetic"}}'
    )


def test_plant_guard_detects_original_contexts_from_vector() -> None:
    plant_id = _load_audit_vectors()["plant_ids"][0]

    assert _has_unapproved_plant_identifier(f"plant {plant_id}")
    assert _has_unapproved_plant_identifier(
        f'{{"id": {plant_id}, "stationName": "Synthetic"}}'
    )


@pytest.mark.parametrize(
    ("content", "identifier"),
    (
        ("sensor.flexboss21_synth0a123_entity", "synth0a123"),
        ("18kPV 9876543210 firmware", "9876543210"),
    ),
)
def test_serial_guard_detects_audited_tokens_in_original_contexts(
    monkeypatch: pytest.MonkeyPatch, content: str, identifier: str
) -> None:
    monkeypatch.setattr(
        sys.modules[__name__],
        "AUDITED_DEVICE_IDENTIFIER_DIGESTS",
        frozenset({_fingerprint(identifier)}),
    )

    assert _has_unapproved_device_identifier("docs/example.md", content)


@pytest.mark.parametrize(
    "content",
    (
        '"name": "987 Synthetic Avenue"',
        "name=987+Synthetic+Avenue",
        "switch.station_987_synthetic_avenue_daylight_saving_time",
        "longitude=-121.98765",
        "latitude=38.76543",
    ),
)
def test_location_guard_detects_synthetic_values_by_injected_digest(
    monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    candidates = list(_location_candidates(content))
    assert candidates
    monkeypatch.setattr(
        sys.modules[__name__],
        "AUDITED_LOCATION_DIGESTS",
        frozenset({_location_fingerprint(candidate) for candidate in candidates}),
    )

    assert _has_unapproved_location(content)


def test_location_guard_detects_original_shapes_from_vector() -> None:
    vectors = _load_audit_vectors()

    assert all(
        _has_unapproved_location(shape) for shape in vectors["location_leak_shapes"]
    )


def test_tracked_text_reader_uses_staged_blob_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("staged content\n")
    subprocess.run(("git", "add", "tracked.txt"), cwd=tmp_path, check=True)
    tracked.write_text("unstaged sensitive content\n")
    monkeypatch.setattr(sys.modules[__name__], "REPOSITORY_ROOT", tmp_path)

    blobs = {
        path: content for path, content, error in _tracked_text_blobs() if not error
    }

    assert blobs["tracked.txt"] == "staged content\n"


def test_full_mac_guard_detects_audited_value_but_allows_vendor_oui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic_mac = "02:11:22:33:44:55"
    monkeypatch.setattr(
        sys.modules[__name__],
        "AUDITED_MAC_DIGESTS",
        frozenset({_fingerprint(synthetic_mac)}),
    )

    assert _has_audited_mac(synthetic_mac)
    assert not _has_audited_mac("Vendor OUIs: 00:30:60, 00:30:6a, b0:81:84")


@pytest.mark.parametrize(
    "path",
    (
        "docs/site/example.md",
        "src/generated/example.py",
        "fixtures/build/example.txt",
        "fixtures/credentials/example.txt",
        "fixtures/secrets/example.txt",
    ),
)
def test_sensitive_directory_names_are_not_globally_excluded(path: str) -> None:
    assert not _excluded_path(path)


def test_config_flow_scan_default_must_be_private() -> None:
    content = 'DEFAULT_SCAN_NETWORK = "192.0.2.0/24"\n'

    assert _has_operational_identity_default(
        "custom_components/eg4_web_monitor/_config_flow/scanner.py", content
    )
    assert not _has_operational_identity_default(
        "custom_components/eg4_web_monitor/_config_flow/scanner.py",
        'DEFAULT_SCAN_NETWORK = "192.168.1.0/24"\n',
    )
