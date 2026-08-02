#!/usr/bin/env python3
"""Test runner for EG4 Inverter integration."""

import argparse
import subprocess
import sys
from pathlib import Path


def _normalized_exit_code(returncode: int) -> int:
    """Return a shell-safe failure code for subprocess signal termination."""
    if returncode < 0:
        return 1
    return returncode


def install_test_requirements() -> None:
    """Install test requirements."""
    requirements_file = Path(__file__).with_name("requirements-test.txt")
    if not requirements_file.exists():
        raise FileNotFoundError(f"Test requirements not found: {requirements_file}")

    print("📦 Installing test requirements...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)],
        check=True,
    )
    print("✅ Test requirements installed")


def run_tests(
    coverage: bool = False, verbose: bool = False, test_filter: str | None = None
) -> int:
    """Run the test suite."""
    # Now run_tests.py is in the tests directory
    tests_dir = Path(__file__).parent
    integration_root = tests_dir.parent

    # Build pytest command
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(tests_dir / "pytest.ini"),
    ]

    if coverage:
        cmd.extend(
            [
                "--cov=custom_components/eg4_web_monitor",
                "--cov-report=html:htmlcov",
                "--cov-report=term-missing",
                "--cov-fail-under=80",
            ]
        )

    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")

    # Add asyncio mode for async tests
    cmd.extend(["-p", "pytest_asyncio"])

    # Add test directory
    cmd.append(str(tests_dir))

    # Add test filter if specified
    if test_filter:
        cmd.extend(["-k", test_filter])

    print(f"🧪 Running tests: {' '.join(cmd[2:])}")

    try:
        result = subprocess.run(cmd, cwd=integration_root, check=False)
        if result.returncode == 0:
            print("✅ All tests passed!")
            if coverage:
                print("📊 Coverage report generated in htmlcov/")
        else:
            print("❌ Some tests failed")
        return _normalized_exit_code(result.returncode)
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return 1


def run_linting() -> int:
    """Run the canonical Ruff lint and formatting checks."""
    print("🔍 Running code linting...")

    integration_root = Path(__file__).parent.parent
    checks = (
        ("Ruff lint", [sys.executable, "-m", "ruff", "check", "."]),
        (
            "Ruff format",
            [sys.executable, "-m", "ruff", "format", "--check", "."],
        ),
    )

    try:
        for label, command in checks:
            result = subprocess.run(
                command,
                cwd=integration_root,
                check=False,
            )
            if result.returncode != 0:
                print(f"❌ {label} failed (exit {result.returncode})")
                return _normalized_exit_code(result.returncode) or 1
    except OSError as err:
        print(f"❌ Could not run Ruff: {err}")
        return 1

    print("✅ Code linting and formatting passed!")
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test runner for EG4 Inverter integration"
    )
    parser.add_argument(
        "--install", action="store_true", help="Install test requirements"
    )
    parser.add_argument(
        "--coverage", action="store_true", help="Generate coverage report"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--filter", "-k", help="Filter tests by pattern")
    parser.add_argument("--lint", action="store_true", help="Run code linting")
    parser.add_argument(
        "--all", action="store_true", help="Run all checks (tests, coverage, linting)"
    )

    args = parser.parse_args()

    if args.install:
        try:
            install_test_requirements()
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"❌ Failed to install requirements: {e}")
            return 1

    exit_code = 0

    if args.all:
        args.coverage = True
        args.lint = True

    if not any([args.install, args.lint]) or args.all:
        # Run tests by default
        test_result = run_tests(
            coverage=args.coverage, verbose=args.verbose, test_filter=args.filter
        )
        exit_code = max(exit_code, test_result)

    if args.lint or args.all:
        lint_result = run_linting()
        exit_code = max(exit_code, lint_result)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
