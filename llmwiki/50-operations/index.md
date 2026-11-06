# 50-operations — running and shipping

## Pages

* [Dev environment](dev-environment.md) - Local setup, the HA container, four-mode testing and its hazards. Owns: Dev setup; bind mounts; four-mode testing; mode-switch hazards.
* [Quality gates](quality-gates.md) - What must pass before a commit, and what only advises. Owns: Lint, format, typecheck, tests, coverage, tier validators; blocking vs advisory CI.
* [Release process](release-process.md) - Two-repo release ordering and the pin-move gate. Owns: Release ordering; artifact-trust gate; version scheme; manifest pin coupling; HACS publish.
* [Issue and PR pipeline](issue-pipeline.md) - Issue templates, log enforcement, PR conventions. Owns: Issue templates; debug-log auto-close; PR conventions; work-tracking prohibitions.
