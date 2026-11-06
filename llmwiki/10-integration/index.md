# 10-integration — the Home Assistant integration

## Pages

* [Integration architecture](architecture.md) - Module inventory by layer, coordinator mixin composition, setup/unload sequence. Owns: Module inventory; mixin composition and MRO constraints; config-entry lifecycle; smart-port read identity and registry authority.
* [Config flow](config-flow.md) - The `_config_flow` package, real step names, connection-type derivation. Owns: Package layout and shim; step names; connection-type derivation; unique-id construction and migration.
* [Controls and writes](controls-and-writes.md) - How a control write reaches a device, and how to derive each mechanism's population. Owns: The control-write mechanisms; write routing; local-vs-cloud decision; optimistic state and TTL; post-write refresh; error surfacing.
* [Data flow by connection mode](data-flow-by-mode.md) - HTTP / LOCAL / HYBRID end to end, and why HYBRID is not a third code path. Owns: Per-mode data flow; poll intervals, throttles and cache TTLs; the LOCAL static first-refresh phase.
* [Data semantics — the rules behind this project's repeated regressions](data-semantics.md) - What values mean and the traps in interpreting them. Owns: Staleness, carry-forward, eviction; capability gating by family; energy monotonicity and the clamp ban; daily-energy diagnostic lineage; float tolerance; battery accumulation by serial; direct battery projection and cell-voltage presentation; parameter cache seeding; the `time.monotonic()` fresh-boot trap.
* [Entities: inheritance, identity, availability](entities-identity-availability.md) - Entity base classes, and why `unknown` and `unavailable` differ by class. Owns: Base-class graph; per-class availability semantics; unique-id formats as implemented; entity-id derivation.
* [Diagnostics, Repairs, and device removal](diagnostics-repairs.md) - Diagnostics output, redaction, and the Repairs surface. Owns: Diagnostics shape and redaction; serial/plant aliasing; repairs issue keys; device-removal ledger.
