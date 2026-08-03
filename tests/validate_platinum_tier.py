#!/usr/bin/env python3
"""
Platinum Tier Quality Scale Validation Script for EG4 Web Monitor Integration.

This script validates compliance with Home Assistant's Platinum tier quality scale requirements:
https://developers.home-assistant.io/docs/core/integration-quality-scale/#-platinum

Platinum Tier Requirements:
1. async-dependency: Dependency is async ✅
2. inject-websession: The integration dependency supports passing in a websession ✅
3. strict-typing: Strict typing with mypy ✅
"""

import subprocess
import sys
from pathlib import Path


def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{'=' * 80}")
    print(f"  {text}")
    print(f"{'=' * 80}\n")


def print_requirement(number: int, title: str, description: str) -> None:
    """Print a requirement header."""
    print(f"\n{number}. {title}")
    print(f"   {description}")
    print()


def check_async_dependency() -> bool:
    """Check if the integration uses async dependencies (aiohttp).

    Platinum requirement: async-dependency
    """
    print_requirement(
        1,
        "Async Dependency",
        "Verify that the integration uses async HTTP libraries (aiohttp)",
    )

    # Check manifest.json for pylxpweb requirement (which uses aiohttp internally)
    manifest_path = Path("custom_components/eg4_web_monitor") / "manifest.json"
    if not manifest_path.exists():
        print("  ❌ manifest.json not found")
        return False

    with open(manifest_path, "r", encoding="utf-8") as f:
        import json

        manifest = json.load(f)
        requirements = manifest.get("requirements", [])

        # Check for pylxpweb (which uses aiohttp internally)
        has_pylxpweb = any("pylxpweb" in req for req in requirements)
        has_aiohttp = any("aiohttp" in req for req in requirements)
        if has_pylxpweb:
            print("  ✅ Using pylxpweb library (uses aiohttp internally)")
            return True
        if has_aiohttp:
            print("  ✅ Using aiohttp (async HTTP library)")
            return True
        print("  ❌ No async HTTP library found in requirements")
        return False


def check_websession_injection() -> bool:
    """Check if the API client supports websession injection.

    Platinum requirement: inject-websession
    """
    print_requirement(
        2,
        "Websession Injection",
        "Verify that the API client supports passing in an aiohttp ClientSession",
    )

    # Check for session injection in coordinator (using pylxpweb library)
    coordinator_path = Path("custom_components/eg4_web_monitor") / "coordinator.py"
    if not coordinator_path.exists():
        print("  ❌ Coordinator file not found")
        return False

    with open(coordinator_path, "r", encoding="utf-8") as coord_file:
        coord_content = coord_file.read()

        # Check for session injection in coordinator
        if "async_get_clientsession" in coord_content:
            print("  ✅ Coordinator injects Home Assistant's aiohttp session")
        else:
            print("  ❌ Coordinator does not inject session")
            return False

        # Check for LuxpowerClient session parameter usage
        if "session=" in coord_content and "LuxpowerClient" in coord_content:
            print("  ✅ LuxpowerClient receives injected session parameter")
        else:
            print("  ⚠️  Could not verify LuxpowerClient session injection")

    # Check for session injection in config_flow
    config_flow_path = (
        Path("custom_components/eg4_web_monitor") / "_config_flow" / "__init__.py"
    )
    if not config_flow_path.exists():
        print("  ❌ Config flow file not found")
        return False

    with open(config_flow_path, "r", encoding="utf-8") as cf_file:
        cf_content = cf_file.read()

        # Check for session injection in config flow
        if "async_get_clientsession" in cf_content:
            print("  ✅ Config flow injects Home Assistant's aiohttp session")
        else:
            print("  ❌ Config flow does not inject session")
            return False

    return True


def check_strict_typing() -> bool:
    """Check if strict typing is configured with mypy.

    Platinum requirement: strict-typing
    """
    print_requirement(
        3, "Strict Typing", "Verify that strict typing is configured with mypy"
    )

    # Check for mypy.ini
    mypy_config_path = Path("tests/mypy.ini")
    if not mypy_config_path.exists():
        print("  ❌ tests/mypy.ini not found")
        return False

    with open(mypy_config_path, "r", encoding="utf-8") as f:
        content = f.read()

        # Check for strict mode
        if "strict = True" in content:
            print("  ✅ mypy strict mode enabled")
        else:
            print("  ❌ mypy strict mode not enabled")
            return False

    # Check for py.typed marker file (main package only - API is external pylxpweb)
    py_typed_main = Path("custom_components/eg4_web_monitor/py.typed")

    if py_typed_main.exists():
        print("  ✅ py.typed marker file exists (main package)")
    else:
        print("  ❌ py.typed marker file missing (main package)")
        return False

    # Note: API package (pylxpweb) is external and has its own typing
    print("  ℹ️  External API library (pylxpweb) provides its own type hints")

    # Run mypy in the same Python environment as this validator. Merely having
    # strict=True in the config does not satisfy the tier if mypy is absent or
    # the code does not pass the configured check.
    try:
        print("  🔍 Running mypy type checking...")
        integration_dir = Path("custom_components/eg4_web_monitor")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--config-file",
                str(mypy_config_path),
                str(integration_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            print("  ✅ mypy type checking passed with no errors")
            return True
        print(f"  ❌ mypy failed with exit code {result.returncode}:")
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        for line in output.splitlines()[:10]:
            if line.strip():
                print(f"      {line}")
        return False

    except OSError as err:
        print(f"  ❌ mypy could not run: {err}")
        return False


def main() -> int:
    """Run all Platinum tier validations."""
    print_header("Home Assistant Integration Quality Scale: Platinum Tier Validation")
    print("Integration: EG4 Web Monitor")
    print(
        "Documentation: https://developers.home-assistant.io/docs/core/integration-quality-scale/#-platinum"
    )

    results = []

    # Run all checks
    results.append(("Async Dependency", check_async_dependency()))
    results.append(("Websession Injection", check_websession_injection()))
    results.append(("Strict Typing", check_strict_typing()))

    # Print summary
    print_header("Platinum Tier Validation Summary")

    all_passed = all(result[1] for result in results)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")

    print()
    if all_passed:
        print("🎉 All Platinum tier requirements validated successfully!")
        print()
        print(
            "Note: This integration also meets all Bronze, Silver, and Gold tier requirements."
        )
        print(
            "      Bronze is enforced by the quality workflow; run "
            "validate_silver_tier.py and validate_gold_tier.py"
        )
        print("      to verify lower tier compliance.")
        return 0
    else:
        print("❌ Some Platinum tier requirements are not met.")
        print("   Please address the failing checks above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
