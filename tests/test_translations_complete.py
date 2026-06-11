"""Locale parity gate: every translation file carries every strings.json key.

Promoted from tests/validate_translations.py into the pytest suite (eg4-8hs3)
so locale gaps can never land silently again — the beta.3 attach-retry work
shipped 29 exceptions.*/issues.* keys in en only, and nothing failed.

Also pins placeholder integrity: a translated string must use exactly the
same ``{placeholder}`` set as the English source, otherwise Home Assistant's
translation formatting raises at display time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "eg4_web_monitor"
TRANSLATIONS = COMPONENT / "translations"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _load(path: Path) -> dict[str, str]:
    return _flatten(json.loads(path.read_text()))


def _locales() -> list[Path]:
    return sorted(TRANSLATIONS.glob("*.json"))


STRINGS = _load(COMPONENT / "strings.json")


@pytest.mark.parametrize("locale_file", _locales(), ids=lambda p: p.stem)
def test_locale_has_every_key(locale_file: Path) -> None:
    """Each locale must contain every key path present in strings.json."""
    locale = _load(locale_file)
    missing = sorted(set(STRINGS) - set(locale))
    assert not missing, (
        f"{locale_file.stem} is missing {len(missing)} keys: {missing[:10]}"
    )


@pytest.mark.parametrize("locale_file", _locales(), ids=lambda p: p.stem)
def test_locale_has_no_stale_keys(locale_file: Path) -> None:
    """Locales must not carry keys that no longer exist in strings.json.

    Catches the reverse drift: a source key renamed or deleted leaves
    orphaned translations behind in every locale.
    """
    locale = _load(locale_file)
    stale = sorted(set(locale) - set(STRINGS))
    assert not stale, f"{locale_file.stem} has {len(stale)} stale keys: {stale[:10]}"


@pytest.mark.parametrize("locale_file", _locales(), ids=lambda p: p.stem)
def test_locale_placeholders_match_english(locale_file: Path) -> None:
    """Translated strings must keep the exact English placeholder set."""
    locale = _load(locale_file)
    mismatched = []
    for key, en_value in STRINGS.items():
        if key not in locale or not isinstance(en_value, str):
            continue
        want = sorted(_PLACEHOLDER.findall(en_value))
        got = sorted(_PLACEHOLDER.findall(str(locale[key])))
        if want != got:
            mismatched.append(f"{key}: en={want} vs {got}")
    assert not mismatched, f"{locale_file.stem} placeholder drift: {mismatched[:5]}"
