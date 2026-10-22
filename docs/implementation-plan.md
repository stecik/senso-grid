# SensoGrid implementation plan

> Agent workflow: olc-powers:subagent-driven-development with independent frontend/backend tasks via dispatching-parallel-agents; whole-branch review before completion.
Goal: runnable self-hosted mobile-first climate monitor matching docs/requirements.md and docs/contract.md.
Architecture: Vue static PWA in FastAPI process, SQLite metadata, InfluxDB3 measurements, async BLE driver and collector, optional Web Push.
User approved work and routine decisions; no extra approval gate. No commit/push/deploy.

- [x] Contract/spec and source evidence (root)
- [x] Backend auth, SQLite migrations/configuration, validated floorplan API, alerts/push, tests (backend agent)
- [x] Vue PWA dashboard/history/editor/alerts/settings and frontend checks (frontend agent)
- [x] BLE protocol/collector, Influx3 query adapter, tests (root)
- [x] Compose/Docker, env examples, README and CI (root)
- [x] Integrate, run tests/lint/typecheck/build, actual sensor and Docker verification where available
- [x] Independent review, repair findings, final result and bounded limitations

Global constraints: no APK retained; no invented protocol; use actual FFE5/FFE8/FFE9 and A2 query confirmed in hardware; store raw battery state without invented percentage. UTC and stable IDs, no history in SQLite. Simulation explicit. Core query chunks48h; weighted merge across chunks. Avoid privileged containers; mount host BlueZ/D-Bus. No credentials committed.

Review focus: integration contracts, authorization and setup race, shared SQLite atomicity, removed-room preservation, stale/no-data behavior, collector bounded scan/connections/cleanup, weighted history stats/month boundaries, push network dependency and SSRF, UI import preview and editor touch paths, container permissions/readiness.

Execution completed; see docs/verification.md for current evidence and environment limitations. Final source integrated into primary main checkout without a commit.
