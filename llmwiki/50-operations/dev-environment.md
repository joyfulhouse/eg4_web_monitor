---
canonical-for: local development setup, HA docker bind mounts, four-mode testing, mode switch hazards
sources:
  - /tmp/llmwiki-research/repo-operations.md
  - docs/DEVELOPMENT.md
  - CLAUDE.md
  - ../docker-compose.yaml (parent homeassistant-dev)
  - ../scripts/eg4-switch-mode.sh (parent homeassistant-dev)
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Dev environment

How an agent develops against this two-repo stack: **eg4_web_monitor** (this repo) and **pylxpweb** (sibling library). Do not guess paths or modes — use the tables and commands below.

## Python tooling (`uv`)

**verified-against-code** — `docs/DEVELOPMENT.md:11-18`

```bash
git clone https://github.com/joyfulhouse/eg4_web_monitor.git
cd eg4_web_monitor
uv venv --python 3.13
source .venv/bin/activate
uv pip install -r tests/requirements-test.txt
```

Agent day-to-day commands prefer `uv run` (no activate required) — **verified-against-code** — `CLAUDE.md` Testing section / `prek.toml` mypy hook.

Pinned quality tools — **verified-against-code** — `tests/requirements-test.txt:19-21`:

| Package | Pin | Why |
|---------|-----|-----|
| `mypy` | `2.3.0` | Keep in sync with `quality-validation.yml` |
| `ruff` | `0.15.5` | Keep in sync with `prek.toml` and CI; 0.16 broke CI (#482) |

### pylxpweb sibling setup

**verified-against-code** — pylxpweb `docs/DEVELOPMENT.md` (sibling repo):

```bash
cd ../python/pylxpweb   # relative to homeassistant-dev/
uv sync
uv run pytest
uv run ruff check
uv run ruff format
uv run mypy
```

## Home Assistant docker container

Lives in the **parent** repo `homeassistant-dev/` (sibling of this clone), not inside eg4_web_monitor.

| Fact | Value | Grade |
|------|-------|-------|
| Compose file | `homeassistant-dev/docker-compose.yaml` | verified-against-code — compose L14–36 |
| Service / container | `homeassistant` / `homeassistant-dev` | verified-against-code |
| Image | `homeassistant/home-assistant:latest` | verified-against-code |
| UI port | `8123` → http://localhost:8123 | verified-against-code |

### Bind mounts (host → container)

**verified-against-code** — `homeassistant-dev/docker-compose.yaml:24-28`

| Host path (from `homeassistant-dev/`) | Container path | Purpose |
|---------------------------------------|----------------|---------|
| `./eg4_web_monitor/custom_components/eg4_web_monitor` | `/config/custom_components/eg4_web_monitor` | Live integration code |
| `../python/pylxpweb/src/pylxpweb` | `/usr/local/lib/python3.13/site-packages/pylxpweb` | Live library source over site-packages |
| Mode-selected `./config*` | `/config` | HA config directory (see modes below) |

Code is bind-mounted; **Python import changes still require a container restart** because the interpreter already loaded modules — **verified-against-code** — `CLAUDE.md` Docker section.

```bash
# Soft restart after import changes (integration or pylxpweb)
docker restart homeassistant-dev
docker logs -f homeassistant-dev

# Full recreate after compose edit / mode switch (script does this)
cd ../   # homeassistant-dev/
docker-compose down && docker-compose up -d
```

End-user install is HACS zip (`INSTALL.md` / `hacs.json`); agents use the docker mounts above, not HACS — **inferred** from `docs/DEVELOPMENT.md` + `hacs.json`.

## Four test modes

`CLAUDE.md` documents three modes. Compose and the switch script also support a fourth — **verified-against-code** — `homeassistant-dev/docker-compose.yaml:4-12`, `homeassistant-dev/scripts/eg4-switch-mode.sh:20-41`.

| Mode | Config dir (from `homeassistant-dev/`) | Purpose |
|------|------------------------------------------|---------|
| `cloud` | `./config` | Baseline / reference |
| `local` | `./config-local` | Local-only (Modbus TCP or WiFi dongle) |
| `hybrid` | `./config-hybrid` | Local poll + cloud supplemental data |
| `local-nomidbox` | `./config-local-nomidbox` | Local without GridBOSS (inverters only) |

### Validation expectations

**verified-against-code** — `CLAUDE.md` Multi-Mode Testing section:

| Mode | Expectation |
|------|-------------|
| Cloud | Baseline; should match production |
| Local | Must have **all entities present in cloud** (minimum parity) |
| Hybrid | Polls locally with cloud supplemental data |
| All | Small margin OK for live readings (cloud lag) |

Configs share HA user accounts/UI (copied from `./config`); each config has the EG4 entry removed for fresh configuration — **verified-against-code** — `CLAUDE.md`.

## Mode switch script

**File:** `homeassistant-dev/scripts/eg4-switch-mode.sh`
**verified-against-code** — script lines 20–74

What it actually does:

1. Maps `cloud|local|hybrid|local-nomidbox` → config directory.
2. `sed -i.bak` rewrites the `*:/config` volume line in `docker-compose.yaml` for all known variants (leaves `docker-compose.yaml.bak` beside compose).
3. Verifies the new path appears in compose.
4. `docker-compose down` then `docker-compose up -d` (full stack restart, not soft reload).
5. Prints access URL and log hint.

```bash
cd homeassistant-dev/   # parent of eg4_web_monitor
./scripts/eg4-switch-mode.sh cloud            # or local | hybrid | local-nomidbox

# Check current mode
grep ":/config" docker-compose.yaml | head -1
```

**sed order hazard:** `config-local-nomidbox` must be rewritten **before** `config-local` or a partial match can leave the wrong directory. The script already orders the expressions correctly — **verified-against-code** — `eg4-switch-mode.sh:49-54`.

## Operational hazards (do not skip)

| Hazard | Rule | Grade |
|--------|------|-------|
| One mode at a time | Only one of cloud/local/hybrid/local-nomidbox may run — API rate limits + Modbus collisions | verified-against-code — `CLAUDE.md` |
| Prod owns the gateway | Production runs **HYBRID** and holds the single Modbus/dongle gateway. Stop `homeassistant-dev` before local Modbus/dongle probing or production silently degrades to cloud-fallback | verified-against-code — `docs/reference/firmware/HYBRID_EPS_REGISTERS.md` (~303–304) |
| Dongle single-client | Scripts that talk to the dongle (e.g. `scripts/probe_gridboss_nbu_regs.py`) require HA stopped or cloud-only mode | verified-against-code — probe script header / research dossier |
| pylxpweb dist-info loss | After a mode switch, a fresh container layer can lack pylxpweb dist-info → HA pip-installs over the bind mount and breaks the integration. Recreate minimal dist-info after EVERY switch if that happens | asserted-unverified in-repo (recorded in CLAUDE.md beta.21 narrative + beads memory); treat as operational fact |
| Mode switch restarts whole stack | Script uses `down`/`up`, not `restart` | verified-against-code — `eg4-switch-mode.sh:67-68` |
| `.bak` left behind | `sed -i.bak` creates `docker-compose.yaml.bak` | verified-against-code — `eg4-switch-mode.sh:49` |

Cross-check helper (parent): `homeassistant-dev/scripts/compare_ha_vs_cloud.py` (HA WebSocket vs cloud API) — **verified-against-code** — file exists in parent `scripts/`.

## Agent copy-paste: live validation

```bash
cd homeassistant-dev/
./scripts/eg4-switch-mode.sh cloud    # or local | hybrid | local-nomidbox
docker logs -f homeassistant-dev
# UI: http://localhost:8123
```

**This wiki page does not authorize starting/stopping docker during docs-only work.** Use these commands only when an operator has asked for live validation.
