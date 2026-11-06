# 20-pylxpweb — the library

## Pages

* [API surface](api-surface.md) - The seams the integration actually uses. Owns: Public client, device-factory and transport-factory seams.
* [Local transports](transports.md) - Modbus TCP and WiFi dongle behaviour. Owns: Local transport behaviour.
* [Models and scaling](models-and-scaling.md) - Portal models, normalized local data, enums, scaling. Owns: Models, missing values, enums and scaling.
* [Write paths](write-paths.md) - How the library routes and verifies a write. Owns: Cloud, local, hybrid and schedule write routing and verification.
* [Release and pinning](release-and-pinning.md) - Version derivation and the dependency pin. Owns: Version derivation and pin mechanics.
