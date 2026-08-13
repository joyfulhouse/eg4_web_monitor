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


# --- #563 M4 semantics gate -------------------------------------------------
#
# Key/placeholder parity cannot catch a *semantic* revert of the
# offgrid_ac_charge_switch_removed Repairs text: the r1 wording (which sent
# local-only users to a Clear Schedule button they never receive) keeps every
# key and placeholder intact, so the tests above stayed green under it. These
# two gates pin the meaning instead, in strings.json and every locale.

_OFFGRID_ISSUE_KEY = "issues.offgrid_ac_charge_switch_removed.description"


def _issue_files() -> list[Path]:
    return [COMPONENT / "strings.json", *_locales()]


@pytest.mark.parametrize("locale_file", _issue_files(), ids=lambda p: p.stem)
def test_offgrid_switch_removed_states_cloud_only_caveat(locale_file: Path) -> None:
    """The Repairs text must state that the Clear AC Charge Schedule button
    requires cloud access and is not created on local-only connections.

    "HTTP" is the locale-invariant marker of the connection-mode
    parenthetical (every shipped translation keeps it verbatim); the English
    source additionally pins the exact caveat phrasing.
    """
    description = _load(locale_file)[_OFFGRID_ISSUE_KEY]
    assert "HTTP" in description, (
        f"{locale_file.stem}: cloud-access requirement missing from "
        "offgrid_ac_charge_switch_removed"
    )
    if locale_file.stem in ("strings", "en"):
        assert "requires cloud access" in description
        assert "not created on local-only connections" in description


@pytest.mark.parametrize("locale_file", _issue_files(), ids=lambda p: p.stem)
def test_offgrid_switch_removed_gives_time_entity_fallback(locale_file: Path) -> None:
    """The Repairs text must give local-only users the time-entity fallback:
    clear the schedule by setting every window's start/end times to 00:00.

    The window-reset pair "00:00–00:00" appears in both the r1 and fixed
    wordings, so the gate looks for a standalone "00:00" outside that pair —
    present only when the fallback instruction exists.
    """
    description = _load(locale_file)[_OFFGRID_ISSUE_KEY]
    without_reset_pair = description.replace("00:00–00:00", "")
    assert "00:00" in without_reset_pair, (
        f"{locale_file.stem}: time-entity fallback (set every window to "
        "00:00) missing from offgrid_ac_charge_switch_removed"
    )
    if locale_file.stem in ("strings", "en"):
        assert "with the time entities instead" in description
