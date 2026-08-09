---
canonical-for: local development setup, HA docker bind mounts, four-mode testing, mode switch hazards
sources:
  - docs/DEVELOPMENT.md
  - CHANGELOG.md
  - prek.toml
  - tests/requirements-test.txt
  - scripts/probe_gridboss_nbu_regs.py
  - docs/reference/firmware/HYBRID_EPS_REGISTERS.md
  - the parent workspace containing this repo — its docker-compose.yaml and
    scripts/ (unversioned; see "The parent workspace cannot be pinned")
  - memory/prod-is-hybrid-dev-contends-modbus.md
  - memory/dev-container-pylxpweb-pin-bump-gotcha.md
  - memory/dev-container-deletes-pylxpweb-src.md
verified-against: 9f6d6e2
last-verified: 2026-08-09
---

# Dev environment

How an agent develops against this two-repo stack: **eg4_web_monitor** (this repo) and **pylxpweb** (sibling library). Do not guess paths or modes — use the tables and commands below.

## Python tooling (`uv`)

The documented setup procedure — `asserted-unverified` — `docs/DEVELOPMENT.md:11-19`. Nothing in the
tree enforces it; the Python floor it states (3.13) is corroborated by CI, which runs the Gold and
Platinum jobs on 3.13 (`verified-against-code` — `.github/workflows/quality-validation.yml`,
`platinum-strict-typing` step **Set up Python 3.13**).

```bash
git clone https://github.com/joyfulhouse/eg4_web_monitor.git
cd eg4_web_monitor
uv venv --python 3.13
source .venv/bin/activate
uv pip install -r tests/requirements-test.txt
```

Agent day-to-day commands prefer `uv run` (no activate required) — `verified-against-code` —
`prek.toml:22`, whose mypy hook runs `uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/`.

Pinned quality tools — `verified-against-code` — `tests/requirements-test.txt:20-21`:

| Package | Pin | Why |
|---------|-----|-----|
| `mypy` | `2.3.0` | Keep in sync with `quality-validation.yml` |
| `ruff` | `0.15.5` | Keep in sync with `prek.toml` and CI; 0.16 broke CI (#482) |

### pylxpweb sibling setup

`asserted-unverified` — pylxpweb `docs/DEVELOPMENT.md` (sibling repo); a documented procedure, not a
tree-enforced one:

```bash
cd ../python/pylxpweb   # relative to homeassistant-dev/
uv sync
uv run pytest
uv run ruff check
uv run ruff format
uv run mypy
```

## The parent workspace cannot be pinned

The docker setup does not live in this repository. It lives in the **parent directory that contains
this clone** — the compose file and the `scripts/` helpers sit one level above `eg4_web_monitor/`.

**That parent directory is not under version control.** It has no `.git`, and no ancestor of it is a
repository either, so there is no commit, tag or version that anyone could cite. Verified by running
`git rev-parse --show-toplevel` from it: it fails with *"not a git repository (or any of the parent
directories)"*.

The consequence is unavoidable and this chapter states it rather than working around it:

> **Every claim on this page sourced from the parent workspace is `asserted-unverified`** — sourced
> from an unversioned local working directory; no durable revision exists to pin, so it cannot be
> code-verified. This holds however precisely the claim is cited.

Line numbers are still given below, because they are genuinely useful to anyone sitting at that
machine. **They are not evidence.** They are offsets into a file that may already differ on any other
machine, that no revision identifies, and that cannot be recovered as it was if it changes. A reader
who cannot open that directory has no way to check any of it.

**This is a real gap, not a formality.** A substantial part of the operations knowledge below — the
container topology, the four modes, the whole mode-switch hazard set — rests on a source only the
maintainer can audit. The knowledge is accurate and worth keeping; it simply is not verifiable by the
standard the rest of this wiki is held to. Treat it as reliable operational lore, and re-read the
actual files before depending on a detail.

Everything else on this page — `prek.toml`, `tests/requirements-test.txt`, `scripts/probe_gridboss_nbu_regs.py`,
`.github/workflows/quality-validation.yml` — is in **this** repo and keeps its grade at `9f6d6e2`.

## Home Assistant docker container

Parent-workspace sourced — `asserted-unverified` throughout, per the section above.

| Fact | Value | Cited at (not evidence) |
|------|-------|-------------------------|
| Compose file | `docker-compose.yaml` in the parent workspace, service block `:14-32` | — |
| Service / container | `homeassistant` / `homeassistant-dev` | `docker-compose.yaml:14-16` |
| Image | `homeassistant/home-assistant:latest` | `docker-compose.yaml:15` |
| UI port | `8123` → http://localhost:8123 | `docker-compose.yaml:29-30` |
| Container Python | 3.13 — `inferred` from the pylxpweb mount targeting `/usr/local/lib/python3.13/site-packages/`; the image tag itself pins no version | `docker-compose.yaml:27` |

### Bind mounts (host → container)

`asserted-unverified` — parent workspace `docker-compose.yaml:21-28`

| Host path (from `homeassistant-dev/`) | Container path | Purpose |
|---------------------------------------|----------------|---------|
| Mode-selected `./config*` (`:23`) | `/config` | HA config directory (see modes below) |
| `./eg4_web_monitor/custom_components/eg4_web_monitor` (`:24`) | `/config/custom_components/eg4_web_monitor` | Live integration code |
| `../python/pylxpweb/src/pylxpweb` (`:27`) | `/usr/local/lib/python3.13/site-packages/pylxpweb` | Live library source over site-packages |

The same container also mounts two unrelated integrations — `intellicenter` (`:25`) and
`brilliant_mqtt` (`:26`) — so restarting it restarts those too — `asserted-unverified` — parent
workspace `docker-compose.yaml:25-26`.

Code is bind-mounted, so an edit lands inside the container immediately — `asserted-unverified` —
parent workspace `docker-compose.yaml:24`, `:27`. **But a running Python process does not re-import a changed
module**, so the edit is live on disk and inert in the running integration until the container
restarts. That gap is the trap: the file is visibly correct, the behavior is visibly old, and it
reads as though the edit failed. Restart before concluding anything about a code change —
`inferred` from the bind mount plus CPython's `sys.modules` caching; nothing in this tree enforces
or asserts it.

```bash
# Soft restart after import changes (integration or pylxpweb)
docker restart homeassistant-dev
docker logs -f homeassistant-dev

# Full recreate after compose edit / mode switch (script does this)
cd ../   # homeassistant-dev/
docker-compose down && docker-compose up -d
```

End-user install is HACS zip (`INSTALL.md` / `hacs.json`); agents use the docker mounts above, not HACS — `inferred` from `docs/DEVELOPMENT.md` + `hacs.json`.

## Four test modes

There are **four** modes — `asserted-unverified` — parent workspace `docker-compose.yaml:5-11`
(mode comment block) and `scripts/eg4-switch-mode.sh:20-43`. The four modes are real and the list is
correct; it is the *grade* that the unversioned source caps, not the knowledge.

**Take the mode list from the script's `case` statement, never from prose.** A mode exists if and
only if it has a `case` arm; the arm is what maps the name to a config directory and what rejects an
unknown name. `local-nomidbox` went undocumented for its entire existence while being fully
supported there, so a prose list that omits a mode is the expected failure, not a surprising one.

| Mode | Config dir (from `homeassistant-dev/`) | Purpose |
|------|------------------------------------------|---------|
| `cloud` | `./config` | Baseline / reference |
| `local` | `./config-local` | Local-only (Modbus TCP or WiFi dongle) |
| `hybrid` | `./config-hybrid` | Local poll + cloud supplemental data |
| `local-nomidbox` | `./config-local-nomidbox` | Local without GridBOSS (inverters only) |

### Validation expectations

Project acceptance criteria for a mode sweep, not properties of any file — no test or CI job
enforces them, so a sweep is evidence only if its result was written down. The most recent one that
was covers the three modes below — `asserted-unverified` — `CHANGELOG.md` 3.4.0-rc.1 ("three-mode
entity-parity sweep passed (cloud/local/hybrid, registry-level)"):

| Mode | Expectation |
|------|-------------|
| Cloud | Baseline; should match production |
| Local | Must have **all entities present in cloud** (minimum parity) |
| Hybrid | Polls locally with cloud supplemental data |
| All | Small margin OK for live readings (cloud lag) |

Each mode is a **separate HA instance** with its own config directory, so entity registries, options
and integration entries do not carry across a switch. None of it is in this repo, so nothing about
those directories is checkable from the tree.

## Mode switch script

**File:** `scripts/eg4-switch-mode.sh` in the parent workspace
`asserted-unverified` — `eg4-switch-mode.sh:12-74` (unversioned source; see
[above](#the-parent-workspace-cannot-be-pinned))

What it actually does:

1. `set -e` at the top: any failing command aborts the switch (`:12`).
2. Maps `cloud|local|hybrid|local-nomidbox` → config directory; anything else prints usage and `exit 1` (`:20-43`).
3. `sed -i.bak` rewrites the `*:/config` volume line in `docker-compose.yaml` for all four variants, leaving `docker-compose.yaml.bak` beside compose (`:49-54`).
4. Greps compose for the new path; `exit 1` if absent (`:57-62`).
5. `docker-compose down` then `docker-compose up -d` — full stack restart, not a soft reload, and it takes the other two integrations down with it (`:66-68`).
6. Prints access URL and log hint (`:70-74`).

```bash
cd homeassistant-dev/   # parent of eg4_web_monitor
./scripts/eg4-switch-mode.sh cloud            # or local | hybrid | local-nomidbox

# Check current mode
grep ":/config" docker-compose.yaml | head -1
```

**The sed expression order does not matter** — a natural worry, since `config-local` is a prefix of
`config-local-nomidbox`. Every pattern ends `:/config`, so `- ./config-local:/config` cannot match
inside `- ./config-local-nomidbox:/config` (the next character there is `-`, not `:`). Chained
rewrites within the one `sed` invocation are idempotent for all four modes, so reordering the
expressions would change nothing — `asserted-unverified` — `eg4-switch-mode.sh:49-54`.

**Real hazard — missing config directory.** The script never checks that the target directory
exists; it edits compose and runs `docker-compose up -d` regardless (`:49-68`,
`verified-against-code`). Docker creates a missing bind-mount source as an empty directory, so a
typo or an un-provisioned mode yields a **fresh, empty Home Assistant** — onboarding screen, no
integration, no entities — rather than an error. Confirm the directory exists before switching —
`inferred` from the absent check plus Docker's bind-mount auto-create behavior.

## Operational hazards (do not skip)

<a id="prod-owns-the-gateway"></a>

### Production owns the Modbus gateway

**Production Home Assistant runs in HYBRID mode and holds the gateway's single allowed connection.
Stop the `homeassistant-dev` container before any local Modbus or dongle probing.** If both clients
compete, production does not error — it silently degrades to cloud-fallback, and the sensors that
only exist on the local transport go stale or unavailable with no alarm.

`asserted-unverified` — `docs/reference/firmware/HYBRID_EPS_REGISTERS.md:303-304` (§8 "Reproducing
this"), corroborated by `memory/prod-is-hybrid-dev-contends-modbus.md`. Both are prose records of an
operational deployment; the production topology is not represented anywhere in this repo, so no code
citation is possible. Treat it as a hard operating rule regardless — the failure mode is silent.

```bash
docker stop homeassistant-dev     # before any local Modbus/dongle probe
docker start homeassistant-dev    # after
```

The bus-level fact that the gateway admits one client is owned by
[`40-hardware/probing-playbook.md`](../40-hardware/probing-playbook.md); this page owns the
dev-environment consequence.

### Remaining hazards

| Hazard | Rule | Grade |
|--------|------|-------|
| One mode at a time | Compose declares exactly one `/config` bind and the script rewrites that single line, so the modes are structurally mutually exclusive — you cannot run two by accident. Running a *second* HA against the same hardware is a different problem, constrained by the single-client gateway ([above](#prod-owns-the-gateway)) | `asserted-unverified` — parent workspace `docker-compose.yaml:23`, `eg4-switch-mode.sh:49-54` |
| Dongle single-client | Scripts that talk to the dongle require HA stopped or in cloud-only mode; `scripts/probe_gridboss_nbu_regs.py` states this in its module docstring under **Requirements** ("No other client connected to the dongle (single-client limitation)", "HA container should be stopped or in cloud-only mode") | `verified-against-code` for the script's stated requirement — `scripts/probe_gridboss_nbu_regs.py:15-19` |
| pylxpweb dist-info loss | After a mode switch, a fresh container layer can lack pylxpweb dist-info → HA pip-installs over the bind mount and breaks the integration. Recreate minimal dist-info after a switch if that happens | `asserted-unverified` — `memory/dev-container-pylxpweb-pin-bump-gotcha.md` |
| Bind-mounted pylxpweb source can be wiped | A `docker restart` has been observed deleting bind-mounted `src/pylxpweb/`; commit before restarting, recover with `git restore src/pylxpweb/` | `asserted-unverified` — `memory/dev-container-deletes-pylxpweb-src.md` |
| Mode switch restarts whole stack | Script uses `down`/`up`, not `restart` | `asserted-unverified` — `eg4-switch-mode.sh:66-68` |
| `.bak` left behind | `sed -i.bak` creates `docker-compose.yaml.bak` on every run | `asserted-unverified` — `eg4-switch-mode.sh:49` |

Cross-check helper: `scripts/compare_ha_vs_cloud.py` in the parent workspace compares HA state
against the cloud API — `asserted-unverified`; it is **not** in this repo (`git cat-file -e
9f6d6e2:scripts/compare_ha_vs_cloud.py` fails), so it carries the same unversioned-source cap.
Not to be confused with `scripts/probe_gridboss_nbu_regs.py`, which **is** tracked here.

## Agent copy-paste: live validation

```bash
cd homeassistant-dev/
./scripts/eg4-switch-mode.sh cloud    # or local | hybrid | local-nomidbox
docker logs -f homeassistant-dev
# UI: http://localhost:8123
```

**This wiki page does not authorize starting/stopping docker during docs-only work.** Use these commands only when an operator has asked for live validation.
