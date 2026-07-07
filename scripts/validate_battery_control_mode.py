#!/usr/bin/env python3
"""Live validation harness for the battery control mode (SOC vs Voltage) feature.

Drives the running Home Assistant dev container via its REST API and confirms
inverter register state independently via the EG4 cloud API (pylxpweb).

Subcommands:
  snapshot   Dump every battery-control entity (state + key attrs) and the live
             cloud register values (reg 179 bits + SOC/voltage limits) to a JSON
             file. Run BEFORE and AFTER changes.
  cloud      Print the live cloud register values only (independent confirmation).
  set-mode   Set Battery Charge/Discharge Control selects to soc|voltage.
  diff       Compare two snapshot JSON files.

Safety: set-mode writes to a REAL inverter. Always snapshot first and restore
to the original regime when done (see the runbook printed by --help-runbook).

Credentials:
  HA_BASE_URL + HA_LONG_LIVED_TOKEN from eg4_web_monitor/.env (REST API).
  EG4 username/password/plant read from the cloud config entry in
  config/.storage/core.config_entries (independent cloud confirmation).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import aiohttp

REPO = Path(__file__).resolve().parents[1]
HA_DEV = REPO.parent  # homeassistant-dev

# Registers we confirm against the cloud (name → register).
SOC_REGISTERS = {
    "HOLD_AC_CHARGE_SOC_LIMIT": 67,
    "HOLD_DISCHG_CUT_OFF_SOC_EOD": 105,
    "HOLD_SOC_LOW_LIMIT_EPS_DISCHG": 125,
    "HOLD_SYSTEM_CHARGE_SOC_LIMIT": 227,
}
VOLT_REGISTERS = {
    "HOLD_SYSTEM_CHARGE_VOLT_LIMIT": 228,
    "HOLD_ON_GRID_EOD_VOLTAGE": 169,
    "HOLD_LEAD_ACID_DISCHARGE_CUT_OFF_VOLT": 100,
    "HOLD_AC_CHARGE_START_BATTERY_VOLTAGE": 158,
    "HOLD_AC_CHARGE_END_BATTERY_VOLTAGE": 159,
}
REGIME_PARAMS = ("FUNC_BAT_CHARGE_CONTROL", "FUNC_BAT_DISCHARGE_CONTROL")

# Entity-id substrings identifying the feature's control entities. These match
# the HA-generated entity_ids (derived from display names: "Cut-Off"→cut_off,
# "Voltage"→voltage), not the unique-id suffixes.
CONTROL_SUFFIXES = (
    "battery_charge_control",
    "battery_discharge_control",
    "system_charge_soc_limit",
    "ac_charge_soc_limit",
    "on_grid_soc_cut_off",
    "off_grid_soc_cut_off",
    "system_charge_voltage_limit",
    "on_grid_cut_off_voltage",
    "off_grid_cut_off_voltage",
    "ac_charge_start_voltage",
    "ac_charge_end_voltage",
)


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    envfile = REPO / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _load_cloud_creds() -> dict[str, Any]:
    """Read EG4 cloud credentials from the HTTP config entry."""
    store = json.loads((HA_DEV / "config/.storage/core.config_entries").read_text())
    for entry in store["data"]["entries"]:
        if entry.get("domain") != "eg4_web_monitor":
            continue
        data = entry.get("data", {})
        if data.get("username") and data.get("password"):
            return {
                "username": data["username"],
                "password": data["password"],
                "base_url": data.get("base_url", "https://monitor.eg4electronics.com"),
                "plant_id": data.get("plant_id"),
                "verify_ssl": data.get("verify_ssl", True),
            }
    raise SystemExit("No EG4 cloud credentials found in config entry")


# ── Home Assistant REST API ──────────────────────────────────────────────────


class HA:
    def __init__(self, base_url: str, token: str, session: aiohttp.ClientSession):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._s = session

    async def states(self) -> list[dict[str, Any]]:
        async with self._s.get(f"{self._base}/api/states", headers=self._headers) as r:
            r.raise_for_status()
            return await r.json()

    async def call(self, domain: str, service: str, data: dict[str, Any]) -> Any:
        async with self._s.post(
            f"{self._base}/api/services/{domain}/{service}",
            headers=self._headers,
            json=data,
        ) as r:
            r.raise_for_status()
            return await r.json()


def _control_entities(states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for st in states:
        eid = st["entity_id"]
        if not (eid.startswith("number.") or eid.startswith("select.")):
            continue
        if any(suf in eid for suf in CONTROL_SUFFIXES):
            out[eid] = {
                "state": st["state"],
                "attributes": {
                    k: st["attributes"].get(k)
                    for k in (
                        "is_effective",
                        "active_control_mode",
                        "control_regime",
                        "unit_of_measurement",
                    )
                    if k in st["attributes"]
                },
            }
    return out


# ── EG4 cloud register read (independent confirmation) ───────────────────────


async def _read_cloud_registers(
    session: aiohttp.ClientSession,
) -> dict[str, dict[str, Any]]:
    from pylxpweb import LuxpowerClient

    creds = _load_cloud_creds()
    client = LuxpowerClient(
        username=creds["username"],
        password=creds["password"],
        base_url=creds["base_url"],
        session=session,
    )
    await client.login()
    result: dict[str, dict[str, Any]] = {}
    try:
        # Discover device serials in the plant via the overview endpoint.
        overview = await client.api.devices.get_devices(int(creds["plant_id"]))
        for device in overview.rows:
            serial = device.serialNum
            regs: dict[str, Any] = {"device_type": device.deviceTypeText}
            # reg 179 regime bits — standard inverters expose FUNC_BAT_*_CONTROL.
            resp = await client.api.control.read_parameters(serial, 179, 1)
            for p in REGIME_PARAMS:
                regs[p] = resp.parameters.get(p)
            # Skip the limit registers for non-inverter devices (GridBOSS/MID),
            # which don't carry the battery regime params.
            if regs[REGIME_PARAMS[0]] is not None or regs[REGIME_PARAMS[1]] is not None:
                for name, reg in {**SOC_REGISTERS, **VOLT_REGISTERS}.items():
                    r = await client.api.control.read_parameters(serial, reg, 1)
                    regs[name] = r.parameters.get(name)
            result[str(serial)] = regs
    finally:
        await client.close()
    return result


# ── Commands ─────────────────────────────────────────────────────────────────


async def cmd_snapshot(args: argparse.Namespace) -> None:
    env = _load_env()
    async with aiohttp.ClientSession() as session:
        ha = HA(env["HA_BASE_URL"], env["HA_LONG_LIVED_TOKEN"], session)
        entities = _control_entities(await ha.states())
        cloud: dict[str, Any] = {}
        if not args.no_cloud:
            try:
                cloud = await _read_cloud_registers(session)
            except Exception as exc:  # noqa: BLE001 - report, don't crash snapshot
                cloud = {"_error": repr(exc)}
    snap = {"mode": args.mode, "entities": entities, "cloud_registers": cloud}
    Path(args.out).write_text(json.dumps(snap, indent=2, sort_keys=True))
    print(
        f"Wrote {args.out}: {len(entities)} control entities, "
        f"{len(cloud)} cloud device(s)"
    )
    for eid in sorted(entities):
        e = entities[eid]
        print(f"  {eid} = {e['state']}  {e['attributes']}")
    if cloud and "_error" not in cloud:
        for serial, regs in cloud.items():
            print(
                f"  [cloud {serial}] "
                f"charge={'V' if regs.get('FUNC_BAT_CHARGE_CONTROL') else 'SOC'} "
                f"discharge={'V' if regs.get('FUNC_BAT_DISCHARGE_CONTROL') else 'SOC'}"
            )
    elif "_error" in cloud:
        print(f"  cloud read error: {cloud['_error']}")


async def cmd_cloud(args: argparse.Namespace) -> None:
    async with aiohttp.ClientSession() as session:
        cloud = await _read_cloud_registers(session)
    print(json.dumps(cloud, indent=2, sort_keys=True))


async def cmd_set_mode(args: argparse.Namespace) -> None:
    env = _load_env()
    target = "Voltage" if args.value == "voltage" else "SOC"
    async with aiohttp.ClientSession() as session:
        ha = HA(env["HA_BASE_URL"], env["HA_LONG_LIVED_TOKEN"], session)
        states = await ha.states()
        targets = [
            eid
            for eid in (s["entity_id"] for s in states)
            if eid.startswith("select.")
            and (
                ("battery_charge_control" in eid and args.side in ("charge", "both"))
                or (
                    "battery_discharge_control" in eid
                    and args.side in ("discharge", "both")
                )
            )
        ]
        if not targets:
            raise SystemExit("No battery control select entities found")
        for eid in targets:
            print(f"set {eid} -> {target}")
            await ha.call(
                "select", "select_option", {"entity_id": eid, "option": target}
            )


def cmd_diff(args: argparse.Namespace) -> None:
    before = json.loads(Path(args.before).read_text())
    after = json.loads(Path(args.after).read_text())
    print(f"DIFF {args.before} -> {args.after}")
    eb, ea = before["entities"], after["entities"]
    for eid in sorted(set(eb) | set(ea)):
        b = eb.get(eid, {}).get("state", "<absent>")
        a = ea.get(eid, {}).get("state", "<absent>")
        flag = "" if b == a else "  <-- changed"
        if flag or args.verbose:
            print(f"  {eid}: {b} -> {a}{flag}")
    cb, ca = before.get("cloud_registers", {}), after.get("cloud_registers", {})
    for serial in sorted(set(cb) | set(ca)):
        for k in sorted(set(cb.get(serial, {})) | set(ca.get(serial, {}))):
            bv = cb.get(serial, {}).get(k)
            av = ca.get(serial, {}).get(k)
            if bv != av or args.verbose:
                mark = "" if bv == av else "  <-- changed"
                print(f"  [cloud {serial}] {k}: {bv} -> {av}{mark}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("snapshot")
    sp.add_argument("--mode", required=True, help="cloud|local|hybrid (label only)")
    sp.add_argument("--out", required=True)
    sp.add_argument("--no-cloud", action="store_true", help="skip cloud confirmation")
    sp.set_defaults(func=lambda a: asyncio.run(cmd_snapshot(a)))

    cp = sub.add_parser("cloud")
    cp.set_defaults(func=lambda a: asyncio.run(cmd_cloud(a)))

    mp = sub.add_parser("set-mode")
    mp.add_argument("value", choices=["soc", "voltage"])
    mp.add_argument("--side", choices=["charge", "discharge", "both"], default="both")
    mp.set_defaults(func=lambda a: asyncio.run(cmd_set_mode(a)))

    dp = sub.add_parser("diff")
    dp.add_argument("before")
    dp.add_argument("after")
    dp.add_argument("--verbose", action="store_true")
    dp.set_defaults(func=cmd_diff)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
