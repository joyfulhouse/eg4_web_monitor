# 30-portal-api — the EG4 cloud portal

## Pages

* [Authentication and session lifecycle](auth-and-session.md) - Login, session lifetime, reauthentication. Owns: Authentication; `JSESSIONID` lifecycle; reauthentication and request encoding.
* [Portal endpoint reference](endpoints.md) - The endpoint inventory and identifier model. Owns: Endpoint inventory; object and identifier model; OpenAPI coverage boundaries.
* [Schemas and scaling](schemas-and-scaling.md) - Response shapes, value scaling, and where sources disagree. Owns: Response shapes; cloud value scaling; parameter read/write representation; schema divergences; GridBOSS generator-energy portal evidence (#658).
* [Errors, retries, rate control and readback limits](errors.md) - Error envelopes, retries, throttling. Owns: Error envelopes; retry and backoff; throttling and cache policy.
