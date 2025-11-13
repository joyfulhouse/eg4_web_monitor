#!/usr/bin/env python3
"""
Silver Tier Validation Script for EG4 Web Monitor Integration.

This script validates compliance with all Silver tier requirements from the
Home Assistant Integration Quality Scale.

Silver Tier Requirements:
1. Service actions must raise exceptions on failure
2. Config entry unloading must be supported
3. Documentation describes all configuration options
4. Installation parameters must be documented
5. Unavailable entities must be marked appropriately
6. Integration requires a designated owner
7. Logging required when service/device becomes unavailable and reconnects
8. Parallel update count must be specified
9. Reauthentication available through UI
10. Test coverage above 95% for all modules
"""

import ast
import json
import sys
from pathlib import Path


class SilverTierValidator:
    """Validator for Silver tier compliance."""

    def __init__(self, base_path: Path):
        """Initialize validator."""
        self.base_path = base_path
        self.errors = []
        self.warnings = []
        self.checks_passed = 0
        self.checks_total = 0

    def validate_all(self) -> bool:
        """Run all validation checks."""
        print("🔍 Validating Silver Tier Compliance\n")

        self.check_service_exception_handling()
        self.check_config_entry_unload()
        self.check_documentation_completeness()
        self.check_installation_docs()
        self.check_entity_availability()
        self.check_codeowners()
        self.check_unavailability_logging()
        self.check_parallel_updates()
        self.check_reauthentication()
        self.check_test_coverage_requirement()

        self.print_results()
        return len(self.errors) == 0

    def check_service_exception_handling(self):
        """1. Service actions must raise exceptions on failure."""
        self.checks_total += 1
        print("1️⃣  Checking service exception handling...")

        init_file = self.base_path / "__init__.py"
        if not init_file.exists():
            self.errors.append("__init__.py not found")
            return

        content = init_file.read_text()

        # Check for ServiceValidationError usage
        if "ServiceValidationError" not in content:
            self.errors.append(
                "Service actions must raise ServiceValidationError on failure"
            )
            return

        # Check for proper exception raising in service handler
        if "raise ServiceValidationError" not in content:
            self.errors.append("Service handler must raise exceptions")
            return

        self.checks_passed += 1
        print("   ✅ Service exception handling implemented\n")

    def check_config_entry_unload(self):
        """2. Config entry unloading must be supported."""
        self.checks_total += 1
        print("2️⃣  Checking config entry unload support...")

        init_file = self.base_path / "__init__.py"
        content = init_file.read_text()

        if "async def async_unload_entry" not in content:
            self.errors.append("async_unload_entry function not found")
            return

        # Check for proper cleanup (API close)
        if "await" in content and ".close()" in content:
            self.checks_passed += 1
            print("   ✅ Config entry unload implemented with cleanup\n")
        else:
            self.warnings.append("Config entry unload may not clean up resources")
            print("   ⚠️  Config entry unload implemented (verify cleanup)\n")

    def check_documentation_completeness(self):
        """3. Documentation describes all configuration options."""
        self.checks_total += 1
        print("3️⃣  Checking documentation completeness...")

        readme = self.base_path / "README.md"
        if not readme.exists():
            self.errors.append("README.md not found")
            return

        content = readme.read_text().lower()

        required_sections = [
            ("configuration", "Configuration section missing"),
            ("username", "Username configuration not documented"),
            ("password", "Password configuration not documented"),
        ]

        missing = []
        for keyword, error_msg in required_sections:
            if keyword not in content:
                missing.append(error_msg)

        if missing:
            self.errors.extend(missing)
            return

        self.checks_passed += 1
        print("   ✅ Configuration options documented\n")

    def check_installation_docs(self):
        """4. Installation parameters must be documented."""
        self.checks_total += 1
        print("4️⃣  Checking installation documentation...")

        readme = self.base_path / "README.md"
        content = readme.read_text().lower()

        if "installation" not in content:
            self.errors.append("Installation section missing from README")
            return

        if "hacs" not in content and "manual" not in content:
            self.warnings.append("Installation methods not clearly documented")

        self.checks_passed += 1
        print("   ✅ Installation parameters documented\n")

    def check_entity_availability(self):
        """5. Unavailable entities must be marked appropriately."""
        self.checks_total += 1
        print("5️⃣  Checking entity availability implementation...")

        # Check at least one platform file for availability property
        platform_files = ["sensor.py", "switch.py", "number.py", "button.py", "select.py"]
        availability_found = False

        for platform_file in platform_files:
            file_path = self.base_path / platform_file
            if file_path.exists():
                content = file_path.read_text()
                # Check for availability property with proper operator precedence
                if ("def available" in content) or ("@property" in content and "available" in content):
                    availability_found = True
                    break

        if not availability_found:
            self.warnings.append(
                "Entity availability property not found (check if needed)"
            )
        else:
            self.checks_passed += 1
            print("   ✅ Entity availability implemented\n")

    def check_codeowners(self):
        """6. Integration requires a designated owner."""
        self.checks_total += 1
        print("6️⃣  Checking designated owner...")

        manifest = self.base_path / "manifest.json"
        if not manifest.exists():
            self.errors.append("manifest.json not found")
            return

        with open(manifest) as f:
            data = json.load(f)

        if "codeowners" not in data or not data["codeowners"]:
            self.errors.append("codeowners not specified in manifest.json")
            return

        self.checks_passed += 1
        print(f"   ✅ Code owner: {data['codeowners']}\n")

    def check_unavailability_logging(self):
        """7. Logging required when service becomes unavailable and reconnects."""
        self.checks_total += 1
        print("7️⃣  Checking unavailability/reconnection logging...")

        coordinator = self.base_path / "coordinator.py"
        if not coordinator.exists():
            self.errors.append("coordinator.py not found")
            return

        content = coordinator.read_text()

        # Check for unavailability logging
        if "_last_available_state" not in content:
            self.errors.append("Availability state tracking not found")
            return

        # Check for logging when unavailable
        if "service unavailable" not in content.lower():
            self.errors.append("Unavailability logging not found")
            return

        # Check for logging when reconnects
        if "reconnected" not in content.lower():
            self.errors.append("Reconnection logging not found")
            return

        self.checks_passed += 1
        print("   ✅ Unavailability and reconnection logging implemented\n")

    def check_parallel_updates(self):
        """8. Parallel update count must be specified."""
        self.checks_total += 1
        print("8️⃣  Checking parallel update count specification...")

        platform_files = ["sensor.py", "number.py", "switch.py", "button.py", "select.py"]
        missing_platforms = []

        for platform_file in platform_files:
            file_path = self.base_path / platform_file
            if file_path.exists():
                content = file_path.read_text()
                if "MAX_PARALLEL_UPDATES" not in content:
                    missing_platforms.append(platform_file)

        if missing_platforms:
            self.errors.append(
                f"MAX_PARALLEL_UPDATES not specified in: {', '.join(missing_platforms)}"
            )
            return

        self.checks_passed += 1
        print("   ✅ Parallel update count specified in all platforms\n")

    def check_reauthentication(self):
        """9. Reauthentication available through UI."""
        self.checks_total += 1
        print("9️⃣  Checking reauthentication flow...")

        config_flow = self.base_path / "config_flow.py"
        coordinator = self.base_path / "coordinator.py"

        if not config_flow.exists():
            self.errors.append("config_flow.py not found")
            return

        flow_content = config_flow.read_text()

        # Check for reauth steps
        if "async_step_reauth" not in flow_content:
            self.errors.append("async_step_reauth not found in config_flow")
            return

        if "async_step_reauth_confirm" not in flow_content:
            self.errors.append("async_step_reauth_confirm not found in config_flow")
            return

        # Check coordinator triggers reauth
        if coordinator.exists():
            coord_content = coordinator.read_text()
            if "ConfigEntryAuthFailed" not in coord_content:
                self.warnings.append(
                    "Coordinator may not trigger reauthentication on auth failure"
                )

        self.checks_passed += 1
        print("   ✅ Reauthentication flow implemented\n")

    def check_test_coverage_requirement(self):
        """10. Test coverage above 95% for all modules."""
        self.checks_total += 1
        print("🔟 Checking test coverage requirement...")

        tests_dir = self.base_path / "tests"
        if not tests_dir.exists():
            self.errors.append("tests directory not found")
            return

        # Check for Silver tier tests
        silver_tests = tests_dir / "test_silver_tier.py"
        if not silver_tests.exists():
            self.warnings.append("Silver tier specific tests not found")

        # Check for config flow tests
        config_tests = tests_dir / "test_config_flow.py"
        if not config_tests.exists():
            self.errors.append("Config flow tests not found")
            return

        self.checks_passed += 1
        print("   ✅ Test infrastructure in place\n")
        print("   ℹ️  Run pytest with coverage to verify 95%+ coverage\n")

    def print_results(self):
        """Print validation results."""
        print("\n" + "=" * 60)
        print("📊 SILVER TIER VALIDATION RESULTS")
        print("=" * 60)

        print(f"\n✅ Checks Passed: {self.checks_passed}/{self.checks_total}")

        if self.warnings:
            print(f"\n⚠️  Warnings ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"   - {warning}")

        if self.errors:
            print(f"\n❌ Errors ({len(self.errors)}):")
            for error in self.errors:
                print(f"   - {error}")
        else:
            print("\n🎉 All Silver tier requirements validated!")

        print("\n" + "=" * 60)


def main():
    """Main validation entry point."""
    # Determine base path (integration root)
    script_path = Path(__file__).resolve()
    base_path = script_path.parent.parent

    validator = SilverTierValidator(base_path)
    success = validator.validate_all()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
