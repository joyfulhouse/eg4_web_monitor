#!/usr/bin/env python3
"""Test runner for EG4 Inverter integration."""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional


def install_test_requirements() -> None:
    """Install test requirements."""
    # Now run_tests.py is in the tests directory, so parent is the integration root
    integration_root = Path(__file__).parent.parent
    requirements_file = integration_root / "requirements-test.txt"
    if requirements_file.exists():
        print("📦 Installing test requirements...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)],
            check=True,
        )
        print("✅ Test requirements installed")
    else:
        print("⚠️  Test requirements file not found")


def run_tests(coverage: bool = False, verbose: bool = False, test_filter: Optional[str] = None) -> int:
    """Run the test suite."""
    # Now run_tests.py is in the tests directory
    tests_dir = Path(__file__).parent
    integration_root = tests_dir.parent

    # Build pytest command
    cmd = [sys.executable, "-m", "pytest"]

    if coverage:
        cmd.extend(
            [
                "--cov=.",
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
        return result.returncode
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return 1


def run_linting() -> int:
    """Run code linting."""
    print("🔍 Running code linting...")

    # Now run_tests.py is in the tests directory, so parent is the integration root
    integration_root = Path(__file__).parent.parent

    # Check if flake8 is available
    try:
        subprocess.run(
            [sys.executable, "-m", "flake8", "--version"],
            capture_output=True,
            check=True,
        )

        # Run flake8 on the integration code
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "flake8",
                ".",
                "--exclude=tests,homeassistant-dev,samples,__pycache__,.git",
                "--max-line-length=120",
                "--ignore=E501,W503",
            ],
            cwd=integration_root,
            check=False,
        )

        if result.returncode == 0:
            print("✅ Code linting passed!")
        else:
            print("⚠️  Code linting issues found")

        return result.returncode

    except subprocess.CalledProcessError:
        print("⚠️  flake8 not available, skipping linting")
        return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Test runner for EG4 Inverter integration")
    parser.add_argument("--install", action="store_true", help="Install test requirements")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--filter", "-k", help="Filter tests by pattern")
    parser.add_argument("--lint", action="store_true", help="Run code linting")
    parser.add_argument("--all", action="store_true", help="Run all checks (tests, coverage, linting)")

    args = parser.parse_args()

    if args.install:
        try:
            install_test_requirements()
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install requirements: {e}")
            return 1

    exit_code = 0

    if args.all:
        args.coverage = True
        args.lint = True

    if not any([args.install, args.lint]) or args.all:
        # Run tests by default
        test_result = run_tests(coverage=args.coverage, verbose=args.verbose, test_filter=args.filter)
        exit_code = max(exit_code, test_result)

    if args.lint or args.all:
        lint_result = run_linting()
        exit_code = max(exit_code, lint_result)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
