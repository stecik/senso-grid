# Xiaomi BTHome collection — 2026-11-06

Implement the user's requested replacement of LT collection with Xiaomi LYWSD03MMC,
pvvx ATC v5.9, unencrypted BTHome v2. Keep historical data and existing assignments.
Old LT modules remain only for historical benchmark scripts and their tests.

Use one continuously running Bleak scanner shared by collection, discovery and
preview. Active advertisement scanning is portable on BlueZ and Windows and does
not establish GATT connections. Do not send commands or read characteristics.
Encrypted/stock Xiaomi advertisements are unsupported and must not appear usable.

Decode FCD2 service data; merge partial objects by canonical MAC. Track climate
timestamps separately from battery/voltage and sightings. Repeated packet IDs do
not create measurements. Invalid, truncated or unsupported frames must not damage
the scanner. Bound discovery memory. Restart the scanner after an adapter error;
never restart BlueZ from the web application.

Review rulings: filter by Service Data inside the callback, not the backend's
advertised-service UUID filter (real WinRT test exposed dropped frames). Restart
the scanner after 120 seconds of global BTHome silence, including empty-radio
environments, to recover silent backend aborts. Deduplicate climate objects
individually. Use persisted climate age independent of discovery cache eviction.
Conservatively discard buffered frames when an assignment change is detected.

Update live data on new climate frames; persist history at the configured per-sensor
interval (60 seconds for new installations). Preserve configured intervals. Manual
refresh waits for a new climate advertisement and does not bypass history cadence.
Availability follows actual climate age. Missing data stays missing. Room changes
require a newly received climate frame; disabled/unregistered devices create no
history. Preserve durable outbox behavior.

Plan (native execution in this Windows checkout; no commits or deployment):

1. Add literal packet fixtures and failure/partial/duplicate tests; implement decoder
   and scanner cache/lifecycle. Run targeted pytest.
2. Replace runtime GATT polling; test live/history cadence, staleness, reassignments,
   cancellation, discovery and fresh previews. Remove obsolete LT runtime tests and
   interval migration; keep demo/outbox and archived driver coverage.
3. Change API/UI protocol and discovery handling, remove obsolete concurrency config,
   include scanner diagnostics, document setup and archived LT troubleshooting.
4. Run full pytest, Ruff, ty, frontend tests/lint/build. Perform a bounded real-radio
   check with the flashed sensor using an isolated data directory; no server changes.

References: https://bthome.io/format/ and
https://bleak.readthedocs.io/en/latest/api/scanner.html.

Completed verification:

- Backend: 120 passed, 1 skipped (opt-in real Influx integration). Existing Starlette
  httpx deprecation warning remains.
- Ruff check, Ruff format check, ty with warnings treated as errors: passed.
- Frontend: 34 tests, lint and production build passed. Existing large chart chunk
  warning remains.
- Real Windows radio: production scanner/collector received 23.94 °C, 42.67 % RH,
  95 % battery at −53 dBm and queued one sample in an isolated test outbox.
- Independent review: four correctness findings reproduced and fixed; follow-up
  review found no further important issue.
- No commits, production data changes, remote deployment or system-service restarts.
