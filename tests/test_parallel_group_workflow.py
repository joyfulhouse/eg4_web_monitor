"""Unified parallel-group GridBOSS workflow (eg4-kh7.2).

``apply_gridboss_to_parallel_group()`` is the single canonical sequence both
the HTTP/HYBRID and LOCAL coordinators call to apply GridBOSS data to a
parallel group:

    overlay GridBOSS CTs -> (LOCAL-only) recompute consumption -> AC-couple PV

These tests lock that shared sequence, the ``recompute_consumption`` flag that
folds the LOCAL-only M3 post-step, and the ordering (consumption is computed
from the pre-AC-couple PV total) so the consolidation cannot silently diverge.
"""

from __future__ import annotations

from custom_components.eg4_web_monitor.coordinator_mixins import (
    _recompute_consumption_from_balance,
    apply_gridboss_to_parallel_group,
)


def test_overlay_applied_in_both_modes() -> None:
    """GridBOSS CT grid_power overlays onto the parallel group regardless of flag."""
    for recompute in (True, False):
        pg = {"pv_total_power": 1000.0, "parallel_battery_power": 0.0}
        gb = {"grid_power": -250.0}
        apply_gridboss_to_parallel_group(
            pg, gb, "A", include_ac_couple=False, recompute_consumption=recompute
        )
        assert pg["grid_power"] == -250.0  # overlaid from authoritative CT


def test_local_recomputes_consumption_http_keeps_value() -> None:
    """recompute_consumption=True replaces consumption_power; False preserves it."""
    gb = {"grid_power": 300.0}  # importing

    # LOCAL: consumption = max(0, pv + (-bat) + grid) = 1000 - 200 + 300 = 1100
    pg_local = {
        "pv_total_power": 1000.0,
        "parallel_battery_power": 200.0,  # charging -> battery_net = -200
        "consumption_power": 99999.0,  # garbage from inverter energy balance
    }
    apply_gridboss_to_parallel_group(
        pg_local, gb, "A", include_ac_couple=False, recompute_consumption=True
    )
    assert pg_local["consumption_power"] == 1100.0

    # HTTP: consumption_power left untouched (cloud value preserved).
    pg_http = {
        "pv_total_power": 1000.0,
        "parallel_battery_power": 200.0,
        "consumption_power": 850.0,  # cloud-provided
    }
    apply_gridboss_to_parallel_group(
        pg_http, gb, "A", include_ac_couple=False, recompute_consumption=False
    )
    assert pg_http["consumption_power"] == 850.0


def test_recomputed_consumption_clamped_non_negative() -> None:
    """Recomputed consumption_power never goes negative."""
    pg = {"pv_total_power": 100.0, "parallel_battery_power": 0.0, "grid_power": -6000.0}
    _recompute_consumption_from_balance(pg, "A")
    # 100 + 0 + (-6000) = -5900 -> clamped to 0.0
    assert pg["consumption_power"] == 0.0


def test_ac_couple_included_only_when_enabled() -> None:
    """AC-couple smart-port PV is added to pv_total_power only when enabled."""
    gb = {
        "smart_port1_status": "ac_couple",
        "ac_couple1_power_l1": 500.0,
        "ac_couple1_power_l2": 500.0,
    }
    pg_on = {"pv_total_power": 1000.0}
    apply_gridboss_to_parallel_group(
        pg_on, gb, "A", include_ac_couple=True, recompute_consumption=False
    )
    assert pg_on["pv_total_power"] == 2000.0  # +1000 AC-couple

    pg_off = {"pv_total_power": 1000.0}
    apply_gridboss_to_parallel_group(
        pg_off, gb, "A", include_ac_couple=False, recompute_consumption=False
    )
    assert pg_off["pv_total_power"] == 1000.0  # unchanged


def test_consumption_uses_pre_ac_couple_pv() -> None:
    """Sequence order: consumption is computed BEFORE AC-couple PV is added."""
    gb = {
        "grid_power": 0.0,
        "smart_port1_status": "ac_couple",
        "ac_couple1_power_l1": 500.0,
        "ac_couple1_power_l2": 0.0,
    }
    pg = {"pv_total_power": 1000.0, "parallel_battery_power": 0.0}
    apply_gridboss_to_parallel_group(
        pg, gb, "A", include_ac_couple=True, recompute_consumption=True
    )
    # consumption uses pv BEFORE ac-couple: 1000 + 0 + 0 = 1000
    assert pg["consumption_power"] == 1000.0
    # pv_total_power AFTER ac-couple: 1000 + 500 = 1500
    assert pg["pv_total_power"] == 1500.0
