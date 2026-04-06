# EG4 Web Monitor — Documentation Index

## Directory Map

```
docs/
├── README.md                    ← You are here
├── DATA_MAPPING.md              — Canonical register-to-sensor mapping (Cloud + Local + Hybrid)
├── architecture/                — Architecture decisions and design docs
│   ├── STRUCTURE.md             — Full project layout (both repos), data flow
│   ├── COMPONENTS.md            — Coordinator mixins, entity classes, pylxpweb integration
│   ├── DST_AUTOMATION_IMPLEMENTATION.md
│   ├── IMPLEMENTATION_SUMMARY.md
│   └── MAINTAINABILITY_ASSESSMENT.md
├── reference/                   — API docs, register maps, scaling tables
│   ├── BATTERY_CURRENT_CONTROL.md
│   ├── MODBUS_DOCS.md
│   ├── PLANT_API_DOCUMENTATION.md
│   └── SCALING_VALIDATION.md
├── plans/                       — Implementation plans (active)
│   ├── archive/                 — Completed plans
│   └── <date>-<topic>-design.md
└── claude/                      — Agent session artifacts
    ├── archive/                 — Historical session notes (pre-2026)
    ├── entity-comparison.md     — 6-way entity validation (Cloud/Local/Hybrid)
    ├── GRIDBOSS_REGISTER_MAP.md — GridBOSS register probe results
    └── MODE_COMPARISON_REPORT.md
```

## What Goes Where

| Content | Location | When to Update |
|---------|----------|----------------|
| Register/sensor mappings | `DATA_MAPPING.md` | Any sensor add/change/rename |
| Architecture decisions | `architecture/` | Major design changes |
| API reference, Modbus maps | `reference/` | New registers or API endpoints |
| Implementation plans | `plans/` | Before starting L/XL features |
| Completed plans | `plans/archive/` | After plan is fully implemented |
| Agent session notes | `claude/` | Active investigations only |
| Old session artifacts | `claude/archive/` | Auto-archived, don't edit |
| Sprint plans | Created by `/sprint-plan` | Each sprint cycle |

## Key References

- **[DATA_MAPPING.md](DATA_MAPPING.md)** — THE canonical reference for all sensor mappings. Consult before any sensor work.
- **[STRUCTURE.md](architecture/STRUCTURE.md)** — Full project layout for both eg4_web_monitor and pylxpweb
- **[COMPONENTS.md](architecture/COMPONENTS.md)** — All components, mixins, entity classes, pylxpweb integration points
- **[Main README](../README.md)** — User-facing installation and setup guide
- **[CLAUDE.md](../CLAUDE.md)** — Development conventions, pylxpweb management, sprint workflow
- **[AGENTS.md](../AGENTS.md)** — Multi-agent workflow and beads integration
- **[CHANGELOG.md](../CHANGELOG.md)** — Release history

## pylxpweb (sibling repo)

The device/API library lives at `/Users/bryanli/Projects/joyfulhouse/python/pylxpweb`.
It is managed from this workspace. See CLAUDE.md > "pylxpweb Library Management" for:
- Development workflow (Docker volume mount)
- Testing commands
- Release process (CI/CD via OIDC)
- Cross-repo fix workflow

## Maintenance Rules

1. **Never duplicate** DATA_MAPPING.md content elsewhere — link to it
2. **Archive completed plans** — move to `plans/archive/` when done
3. **Archive old session docs** — move to `claude/archive/` after 30 days
4. **Keep this index updated** when adding new docs
5. **Plans use date prefix** — `YYYY-MM-DD-<topic>-design.md`
