#!/usr/bin/env python3
"""Validation script for translation string completeness.

Ensures all translation files have the same structure as strings.json
(the source of truth). Checks for:
- Valid JSON in all translation files
- All keys present in every translation file
- No extra keys that don't exist in strings.json
- Structural consistency (nested dicts match)

Usage:
    python tests/validate_translations.py
"""

import json
import sys
from pathlib import Path


def get_all_keys(data: dict[str, object], prefix: str = "") -> set[str]:
    """Recursively extract all dot-delimited key paths from a nested dict."""
    keys: set[str] = set()
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        keys.add(full_key)
        if isinstance(value, dict):
            keys.update(get_all_keys(value, full_key))
    return keys


def get_leaf_keys(keys: set[str]) -> set[str]:
    """Filter a set of dot-delimited key paths to only leaf keys.

    A leaf key is one where no other key in the set starts with it as a prefix.
    For example, given {"a", "a.b", "a.b.c"}, only "a.b.c" is a leaf.
    """
    return {k for k in keys if not any(other.startswith(f"{k}.") for other in keys)}


def _print_key_summary(label: str, keys: set[str], max_display: int = 10) -> None:
    """Print a summary of key differences with truncation."""
    print(f"   {label} {len(keys)} keys:")
    for key in sorted(keys)[:max_display]:
        print(f"     - {key}")
    if len(keys) > max_display:
        print(f"     ... and {len(keys) - max_display} more")


def validate_translations() -> bool:
    """Validate all translation files match strings.json structure."""
    base_dir = Path("custom_components/eg4_web_monitor")
    strings_path = base_dir / "strings.json"
    translations_dir = base_dir / "translations"

    if not strings_path.exists():
        print("❌ strings.json not found")
        return False

    # Load source of truth
    with open(strings_path) as f:
        strings_data = json.load(f)

    source_keys = get_all_keys(strings_data)
    print(f"📋 strings.json has {len(source_keys)} key paths")

    if not translations_dir.exists():
        print("❌ translations/ directory not found")
        return False

    translation_files = sorted(translations_dir.glob("*.json"))
    if not translation_files:
        print("❌ No translation files found")
        return False

    print(f"📁 Found {len(translation_files)} translation files\n")

    all_passed = True

    for trans_file in translation_files:
        lang = trans_file.stem
        try:
            with open(trans_file) as f:
                trans_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ {lang}: Invalid JSON - {e}")
            all_passed = False
            continue

        trans_keys = get_all_keys(trans_data)

        missing = source_keys - trans_keys
        extra = trans_keys - source_keys

        if missing or extra:
            all_passed = False
            print(f"❌ {lang}:")
            if missing:
                _print_key_summary("Missing", get_leaf_keys(missing))
            if extra:
                _print_key_summary("Extra", get_leaf_keys(extra))
        else:
            print(f"✅ {lang}: All {len(source_keys)} keys present")

    return all_passed


def main() -> None:
    """Run translation validation."""
    print("=" * 50)
    print("  Translation String Completeness Check")
    print("=" * 50)
    print()

    passed = validate_translations()

    print()
    if passed:
        print("✅ All translation files are complete and valid")
        sys.exit(0)
    else:
        print("❌ Translation validation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
