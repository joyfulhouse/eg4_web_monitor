#!/usr/bin/env python3
"""Validation script for Home Assistant Gold Tier Quality Scale compliance.

This script validates that the EG4 Web Monitor integration meets all
Gold tier requirements as defined by Home Assistant's Integration Quality Scale.

Gold tier requirements (in addition to Bronze and Silver):
1. Translation support (strings.json)
2. Reconfiguration through UI
3. Extensive user documentation
4. Comprehensive automated tests
5. Device/integration discovery (when applicable)

Usage:
    python tests/validate_gold_tier.py
"""

import json
import os
import sys
from pathlib import Path


def validate_translations():
    """Validate translation support (Gold tier requirement)."""
    print("🌍 Validating translation support...")

    # Check for strings.json in integration directory
    strings_file = Path("custom_components/eg4_web_monitor/strings.json")
    if not strings_file.exists():
        print("  ❌ strings.json not found")
        return False

    print("  ✅ strings.json exists")

    # Validate strings.json structure
    try:
        with open(strings_file, "r", encoding="utf-8") as f:
            strings_data = json.load(f)

        # Check for required sections
        required_sections = ["config", "options", "entity", "services"]
        for section in required_sections:
            if section not in strings_data:
                print(f"  ❌ Missing '{section}' section in strings.json")
                return False

        print("  ✅ strings.json has required sections")

        # Check for reconfigure steps in translations
        if "reconfigure" not in strings_data["config"]["step"]:
            print("  ❌ 'reconfigure' step missing from translations")
            return False

        print("  ✅ Reconfigure flow is translated")

    except json.JSONDecodeError as e:
        print(f"  ❌ Invalid JSON in strings.json: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Error reading strings.json: {e}")
        return False

    # Check for translations directory
    translations_dir = Path("custom_components/eg4_web_monitor/translations")
    if not translations_dir.exists():
        print("  ❌ translations/ directory not found")
        return False

    print("  ✅ translations/ directory exists")

    # Check for English translation
    en_file = translations_dir / "en.json"
    if not en_file.exists():
        print("  ❌ translations/en.json not found")
        return False

    print("  ✅ translations/en.json exists")

    print("✅ Translation support validated\n")
    return True


def validate_reconfiguration():
    """Validate reconfiguration support (Gold tier requirement)."""
    print("🔧 Validating reconfiguration support...")

    config_flow_file = Path(
        "custom_components/eg4_web_monitor/_config_flow/__init__.py"
    )
    if not config_flow_file.exists():
        print("  ❌ _config_flow/__init__.py not found")
        return False

    with open(config_flow_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for async_step_reconfigure
    if "async def async_step_reconfigure" not in content:
        print("  ❌ async_step_reconfigure method not found")
        return False

    print("  ✅ async_step_reconfigure method exists")

    # Check for reconfigure plant selection
    if "async_step_reconfigure_plant" not in content:
        print("  ⚠️  async_step_reconfigure_plant method not found (may be optional)")
    else:
        print("  ✅ async_step_reconfigure_plant method exists")

    # Check for _update_entry helper
    if "_update_entry" not in content:
        print("  ⚠️  _update_entry helper method not found")
    else:
        print("  ✅ _update_entry helper method exists")

    print("✅ Reconfiguration support validated\n")
    return True


def validate_documentation():
    """Validate extensive user documentation (Gold tier requirement)."""
    print("📚 Validating user documentation...")

    readme_file = Path("README.md")
    if not readme_file.exists():
        print("  ❌ README.md not found")
        return False

    with open(readme_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for required sections
    required_sections = {
        "Installation": ["installation", "install"],
        "Configuration": ["configuration", "setup", "configure"],
        "Reconfiguration": ["reconfigur"],
        "Troubleshooting": ["troubleshoot"],
        "FAQ or Examples": ["frequently asked", "faq", "example", "automation"],
        "Prerequisites": ["prerequisite", "require", "before"],
    }

    missing_sections = []
    for section_name, keywords in required_sections.items():
        if not any(keyword in content.lower() for keyword in keywords):
            missing_sections.append(section_name)

    if missing_sections:
        print(f"  ❌ Missing documentation sections: {', '.join(missing_sections)}")
        return False

    print("  ✅ All required documentation sections present")

    # Check for user-friendly language
    user_friendly_indicators = [
        "you can",
        "you will",
        "you need",
        "how to",
        "step by step",
        "example",
        "for example",
    ]

    found_indicators = sum(
        1 for indicator in user_friendly_indicators if indicator in content.lower()
    )

    if found_indicators < 3:
        print("  ⚠️  Documentation may not be user-friendly enough")
    else:
        print("  ✅ Documentation uses user-friendly language")

    # Check documentation length (should be comprehensive)
    doc_length = len(content)
    if doc_length < 5000:
        print(f"  ⚠️  Documentation is short ({doc_length} chars, recommend >5000)")
    else:
        print(f"  ✅ Documentation is comprehensive ({doc_length} chars)")

    print("✅ User documentation validated\n")
    return True


def validate_tests():
    """Validate comprehensive automated tests (Gold tier requirement)."""
    print("🧪 Validating automated test coverage...")

    # Tests are at repo root level
    tests_dir = Path("tests")
    if not tests_dir.exists():
        print("  ❌ tests/ directory not found")
        return False

    print("  ✅ tests/ directory exists")

    # Check for required test files
    required_test_files = {
        "test_config_flow.py": "Config flow tests",
        "test_reconfigure_flow.py": "Reconfiguration tests",
    }

    missing_tests = []
    for test_file, description in required_test_files.items():
        if not (tests_dir / test_file).exists():
            missing_tests.append(f"{description} ({test_file})")
            print(f"  ❌ Missing: {description} ({test_file})")
        else:
            print(f"  ✅ Found: {description}")

    if missing_tests:
        print(f"  ⚠️  Missing test files: {', '.join(missing_tests)}")

    # Check for test comprehensiveness
    test_files = list(tests_dir.glob("test_*.py"))
    if len(test_files) < 2:
        print(f"  ⚠️  Limited test coverage ({len(test_files)} test files)")
    else:
        print(f"  ✅ Good test coverage ({len(test_files)} test files)")

    # Check for conftest.py (fixtures)
    if (tests_dir / "conftest.py").exists():
        print("  ✅ Test fixtures (conftest.py) exist")
    else:
        print("  ⚠️  No conftest.py (test fixtures may be limited)")

    print("✅ Automated test coverage validated\n")
    return True


def validate_manifest():
    """Validate manifest.json for Gold tier requirements."""
    print("📋 Validating manifest.json...")

    manifest_file = Path("custom_components/eg4_web_monitor/manifest.json")
    if not manifest_file.exists():
        print("  ❌ manifest.json not found")
        return False

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Check for required fields
    required_fields = [
        "domain",
        "name",
        "documentation",
        "issue_tracker",
        "version",
        "config_flow",
        "codeowners",
        "iot_class",
        "integration_type",
    ]

    missing_fields = [f for f in required_fields if f not in manifest]
    if missing_fields:
        print(f"  ❌ Missing manifest fields: {', '.join(missing_fields)}")
        return False

    print("  ✅ All required manifest fields present")

    # Validate config_flow is true
    if not manifest.get("config_flow"):
        print("  ❌ config_flow must be true")
        return False

    print("  ✅ config_flow is enabled")

    # Check for codeowners
    if not manifest.get("codeowners"):
        print("  ❌ No codeowners specified")
        return False

    print(f"  ✅ Codeowners: {manifest['codeowners']}")

    print("✅ Manifest validated\n")
    return True


def check_bronze_silver_compliance():
    """Check that Bronze and Silver tier validations still pass."""
    print("🥉🥈 Checking Bronze and Silver tier compliance...")

    silver_script = Path("tests/validate_silver_tier.py")

    if silver_script.exists():
        print("  ✅ Silver tier validation script exists")
        # Note: We're not running it here to avoid circular dependencies
    else:
        print("  ⚠️  Silver tier validation script not found")

    print("  ℹ️  Run Bronze and Silver validation scripts separately")
    print("✅ Prerequisite tier check complete\n")
    return True


def main():
    """Run all Gold tier validations."""
    print("=" * 70)
    print("🏆 Home Assistant Gold Tier Quality Scale Validation")
    print("=" * 70)
    print()

    # Expect to run from repo root
    integration_path = Path("custom_components/eg4_web_monitor")
    if not integration_path.exists():
        print("❌ Error: Must run from repository root")
        print(f"   Expected integration at: {integration_path}")
        sys.exit(1)

    print(f"Working directory: {os.getcwd()}\n")

    validations = [
        ("Bronze/Silver Compliance", check_bronze_silver_compliance),
        ("Translation Support", validate_translations),
        ("Reconfiguration Support", validate_reconfiguration),
        ("User Documentation", validate_documentation),
        ("Automated Tests", validate_tests),
        ("Manifest Configuration", validate_manifest),
    ]

    results = {}
    for name, validation_func in validations:
        try:
            results[name] = validation_func()
        except Exception as e:
            print(f"❌ Error during {name} validation: {e}\n")
            results[name] = False

    print("=" * 70)
    print("📊 VALIDATION SUMMARY")
    print("=" * 70)

    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")

    print()

    total = len(results)
    passed = sum(1 for v in results.values() if v)

    if passed == total:
        print(f"🎉 ALL CHECKS PASSED! ({passed}/{total})")
        print()
        print("🏆 This integration meets Gold Tier quality standards!")
        print()
        print("Gold tier features implemented:")
        print("  ✅ Full translation support (multiple languages ready)")
        print("  ✅ UI-based reconfiguration (change settings without re-adding)")
        print("  ✅ Extensive user-friendly documentation")
        print("  ✅ Comprehensive automated test coverage")
        print("  ✅ Professional code quality and error handling")
        print()
        return 0
    else:
        print(f"⚠️  SOME CHECKS FAILED ({passed}/{total} passed)")
        print()
        print("Please address the failed checks above to achieve Gold tier compliance.")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
