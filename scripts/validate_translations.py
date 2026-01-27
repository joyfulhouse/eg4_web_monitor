#!/usr/bin/env python3
"""Validate that all translation files have matching keys with strings.json.

This script ensures translations stay in sync with the source strings.json file.
Run as part of CI/CD to catch missing translation keys early.
"""

import json
import sys
from pathlib import Path


def get_all_keys(obj: dict, prefix: str = "") -> set[str]:
    """Recursively get all keys from a nested dictionary."""
    keys = set()
    for key, value in obj.items():
        full_key = f"{prefix}.{key}" if prefix else key
        keys.add(full_key)
        if isinstance(value, dict):
            keys.update(get_all_keys(value, full_key))
    return keys


def validate_translations() -> bool:
    """Validate all translation files against strings.json."""
    base_dir = Path(__file__).parent.parent / "custom_components" / "eg4_web_monitor"
    strings_file = base_dir / "strings.json"
    translations_dir = base_dir / "translations"

    if not strings_file.exists():
        print(f"ERROR: strings.json not found at {strings_file}")
        return False

    if not translations_dir.exists():
        print(f"ERROR: translations directory not found at {translations_dir}")
        return False

    # Load source strings
    with open(strings_file, encoding="utf-8") as f:
        source_strings = json.load(f)

    source_keys = get_all_keys(source_strings)
    print(f"Source strings.json has {len(source_keys)} keys")

    # Find all translation files
    translation_files = list(translations_dir.glob("*.json"))
    if not translation_files:
        print("ERROR: No translation files found")
        return False

    print(f"Found {len(translation_files)} translation files")

    all_valid = True
    for trans_file in sorted(translation_files):
        lang = trans_file.stem
        try:
            with open(trans_file, encoding="utf-8") as f:
                trans_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: {lang}.json - Invalid JSON: {e}")
            all_valid = False
            continue

        trans_keys = get_all_keys(trans_data)

        # Check for missing keys in translation
        missing_keys = source_keys - trans_keys
        # Check for extra keys in translation (keys that don't exist in source)
        extra_keys = trans_keys - source_keys

        if missing_keys or extra_keys:
            all_valid = False
            print(f"\n{lang}.json:")
            if missing_keys:
                print(f"  Missing {len(missing_keys)} keys:")
                for key in sorted(missing_keys)[:10]:  # Show first 10
                    print(f"    - {key}")
                if len(missing_keys) > 10:
                    print(f"    ... and {len(missing_keys) - 10} more")
            if extra_keys:
                print(f"  Extra {len(extra_keys)} keys (not in source):")
                for key in sorted(extra_keys)[:10]:
                    print(f"    + {key}")
                if len(extra_keys) > 10:
                    print(f"    ... and {len(extra_keys) - 10} more")
        else:
            print(f"{lang}.json: OK ({len(trans_keys)} keys)")

    return all_valid


def main() -> int:
    """Main entry point."""
    print("Validating translations against strings.json...\n")
    if validate_translations():
        print("\nAll translations are valid!")
        return 0
    else:
        print("\nTranslation validation FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
