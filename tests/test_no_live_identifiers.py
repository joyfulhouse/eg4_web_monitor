"""Regression checks preventing deployment identifiers in tracked examples."""

from __future__ import annotations

import ast
import ipaddress
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]

PROTECTED_FILES = (
    "docs/reference/FIRMWARE_OTA_PROTOCOL.md",
    "docs/reference/firmware/FIRMWARE_OTA_PROTOCOL.md",
    "docs/reference/firmware/re/REGISTER_MAP_FROM_FIRMWARE.md",
    "docs/reference/firmware/re/REGISTER_MAP_LIVE_PROBE.md",
    "docs/reference/firmware_re/REGISTER_MAP_FROM_FIRMWARE.md",
    "docs/reference/firmware_re/REGISTER_MAP_LIVE_PROBE.md",
    "scratchpad/firmware/PACKET_STRUCTURE_ANALYSIS.md",
    "scripts/capture_firmware_upgrade.sh",
    "scripts/collision_test.py",
    "scripts/extract_firmware_registers.py",
    "scripts/monitor_spikes.py",
    "scripts/probe_all_registers.py",
    "scripts/probe_gridboss_nbu_regs.py",
    "tests/test_coordinator_hybrid.py",
    "tests/test_issue_544_offgrid_generator.py",
    "tests/test_issue_548_hybrid_eps_apparent_power.py",
    "tests/test_last_event.py",
    "tests/test_offgrid_registers.py",
    "tests/test_parallel_group_registry_migration.py",
)

OPERATIONAL_PYTHON_SCRIPTS = (
    "scripts/collision_test.py",
    "scripts/extract_firmware_registers.py",
    "scripts/monitor_spikes.py",
    "scripts/probe_all_registers.py",
    "scripts/probe_gridboss_nbu_regs.py",
)

TEST_FIXTURES = tuple(path for path in PROTECTED_FILES if path.startswith("tests/"))

IPV4_PATTERN = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
MAC_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"
)
DEVICE_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9]{10}(?![A-Za-z0-9])"
)
APPROVED_DEVICE_IDENTIFIER = re.compile(
    r"(?:SYNTH[0-9A-Z]{5}|flexboss21)", re.IGNORECASE
)
APPROVED_MAC = re.compile(r"(?i)02:00:00:(?:[0-9a-f]{2}:){2}[0-9a-f]{2}")
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
)


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_protected_examples_use_reserved_network_identities() -> None:
    """Example addresses and MACs must come from approved synthetic domains."""
    for relative_path in PROTECTED_FILES:
        content = _read(relative_path)
        for raw_address in IPV4_PATTERN.findall(content):
            address = ipaddress.ip_address(raw_address)
            assert any(address in network for network in DOCUMENTATION_NETWORKS), (
                f"{relative_path} contains a non-documentation IPv4 address"
            )
        for mac_address in MAC_PATTERN.findall(content):
            assert APPROVED_MAC.fullmatch(mac_address), (
                f"{relative_path} contains a MAC outside the synthetic namespace"
            )


def test_protected_test_fixtures_use_synthetic_device_identifiers() -> None:
    """Device-like test values must be visibly synthetic."""
    for relative_path in TEST_FIXTURES:
        for candidate in DEVICE_IDENTIFIER_PATTERN.findall(_read(relative_path)):
            if any(character.isdigit() for character in candidate):
                if not APPROVED_DEVICE_IDENTIFIER.fullmatch(candidate):
                    raise AssertionError(
                        f"{relative_path} contains a device-like identifier outside "
                        "the synthetic namespace"
                    )


def test_operational_scripts_have_no_identity_defaults() -> None:
    """Operational hosts and device identities must come from runtime input."""
    identity_words = ("HOST", "SERIAL", "INVERTER", "DONGLE", "GRIDBOSS")
    for relative_path in OPERATIONAL_PYTHON_SCRIPTS:
        tree = ast.parse(_read(relative_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for candidate in DEVICE_IDENTIFIER_PATTERN.findall(node.value):
                    if any(character.isdigit() for character in candidate):
                        if not APPROVED_DEVICE_IDENTIFIER.fullmatch(candidate):
                            raise AssertionError(
                                f"{relative_path} contains a device-like literal"
                            )
        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                targets = [
                    target.id
                    for target in statement.targets
                    if isinstance(target, ast.Name)
                ]
                value = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(
                statement.target, ast.Name
            ):
                targets = [statement.target.id]
                value = statement.value
            else:
                continue

            if any(word in target for target in targets for word in identity_words):
                assert not any(
                    isinstance(node, ast.Constant) and isinstance(node.value, str)
                    for node in ast.walk(value)
                ), f"{relative_path} contains a module-level identity default"
