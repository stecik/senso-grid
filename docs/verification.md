# Verification — 2026-10-22

Application source lives directly in C:/Users/marst/Home/it/Projects/SensoGrid on main. Changes are not committed.

## Passed

- Backend: 36 tests passed; one opt-in real InfluxDB test skipped in standard run.
- Frontend: 13 tests passed; ESLint and strict TypeScript/Vite production build passed.
- Ruff lint/format passed before relocation; source preserved, no backend edits during relocation.
- npm audit: zero reported vulnerabilities after upgrading development test runner to Vitest 4.1.12.
- Real InfluxDB 3 Core integration: database creation, empty history, official-client write, multi-window SQL query, weighted month aggregation and historic room attribution passed.
- Docker multi-stage image built from the main checkout.
- Two test containers previously reached healthy; authenticated dashboard/history and static SPA returned 200. Temporary test containers stopped afterward.
- Implemented LT driver read actual LT_7506: 23.7 C and 51.0 % RH. No pairing, clock/unit/reset/firmware command.
- Browser QA: setup/login, all five routes, desktop/mobile, floorplan rename/save, alert creation, language/theme persistence, immediate dirty state, offline shell.
- PWA precache contains shell/assets only; no private API entries.
- Known review findings fixed with focused regressions; targeted independent re-review clear.

## Local preview

http://127.0.0.1:8000 — BLE mode, native Windows process, primary checkout. InfluxDB runs in the sensogrid Docker Compose project, published only to 127.0.0.1:8181. User account, floorplan and sensor configuration were preserved. QA accounts and changes stay in isolated test data. Restart with scripts/start-local.ps1.

## Remaining environment checks

Live Web Push delivery requires actual VAPID identity and browser subscription; not verified. Native Windows BLE was verified; Linux BlueZ/D-Bus permissions on the target Debian host need validation. Long-term battery use, multiple simultaneous physical sensors and extended data-volume performance were not soak-tested.

ECharts is loaded on demand; its compressed chart chunk is about 225 KB, with Vite's size warning. Standard backend tests report a TestClient deprecation warning from Starlette; tests pass.

## Visual redesign

- Replaced split auth/sidebar composition with centered setup/sign-in, cobalt instrument palette, horizontal desktop navigation and navy dark theme. Updated chart colors, app icons and PWA theme.
- ESLint, 13 frontend tests and strict TypeScript/Vite production build passed after final changes.
- Browser verified all routes, light/dark themes, mobile/tablet/desktop (390, 768, 1000, 1280 and 1440 px); no horizontal overflow or JavaScript errors. Unavailable room labels use theme foreground and were verified in dark mode.
- Independent source review found no introduced regression. Browser QA used isolated data on port 8001; primary preview/account data remained untouched. Temporary QA server stopped afterward.

## Password policy update

Setup accepts 8–256 characters and requires an uppercase letter, a lowercase letter and a punctuation/symbol character; digits are optional. Existing passwords remain usable at login. API regressions include exact 8-character passwords, Czech letters, every missing requirement and legacy login. Backend: 45 passed, one optional Influx integration test skipped. Ruff, frontend lint and production build passed. Browser form accepted valid examples and rejected each invalid variant. Local preview restarted with the updated API.

## Physical sensor rollout readiness

- Discovered and successfully queried five deployed sensors: LT_7506 (22.8 C / 51% RH), LT_4AF3 (20.9 C / 52% RH), LT_5A0B (21.3 C / 45% RH), LT_831C (23.1 C / 49% RH), LT_530B (22.9 C / 48% RH). Snapshot around 20:19 Europe/Prague, 2026-10-22; not continuously refreshed in this document. LT_530B RSSI was around -91 dBm.
- Primary application switched to BLE with the existing account/configuration intact; no physical sensors added or assigned automatically, no user floorplan imported.
- Sensor settings and editor options show latest available temperature/humidity, refreshing current server values every five seconds. Physical collection follows configured sampling interval (default 900 seconds).
- Import accepts the schemaVersion/units meters/canvas form and canonical SensoGrid export; normalizes and validates geometry before preview/apply, preserving room IDs.
- Isolated end-to-end QA: native BLE collector read LT_831C, durable InfluxDB write/query returned one real sample, UI displayed 23.1 C / 49% RH, browser imported canvas JSON and assigned sensor to a room. No browser JavaScript errors. QA server stopped.
- Backend 46 passed, one optional integration test skipped; frontend 13 passed, lint and strict production build passed. PowerShell startup script parsed without syntax errors; actual Compose InfluxDB startup reached healthy. Existing Starlette deprecation and ECharts size warnings remain.

## Sensor discovery and compact room fixes

- Discovery results automatically read current measurements one device at a time through a transient authenticated preview endpoint. Preview never registers a sensor or queues history; unavailable measurements show an explicit error and can be retried. BLE access shares the collector lock.
- Real browser QA discovered and displayed three sensors before registration: LT_4AF3 20.8 C / 52% RH, LT_831C 23.1 C / 49% RH, LT_7506 22.8 C / 51% RH. This scan is not a complete inventory; weaker sensors may need another scan. Saved sensor count stayed zero in QA.
- Small rooms retain full names, use compact label sizing, omit the generic editor subtitle, and hide numeric labels when too small; full name/value remains in SVG tooltip and dashboard room list. User-provided pantry geometry (0.7 × 0.6 m) fit label bounds at 1440 and 390 px.
- Disabled buttons use the default cursor instead of wait; unchanged Save verified disabled/default in browser.
- Browser also checked failed preview handling, compact dashboard pantry and mobile overflow (none). Primary account/floorplan/sensors unchanged; QA used isolated data and stopped afterward.
- Backend 47 passed, one optional integration test skipped. Frontend 13 passed; Ruff, ESLint and strict production build passed. Existing dependency/chunk warnings remain.

## Discovery survives temporary sensor outages

- Reproduced prior behavior in browser: failed read removed latest displayed measurements; subsequent empty scan removed the candidate entirely. Registered candidates also exposed a disabled Add action.
- Discovery now merges sightings by case-insensitive BLE address, keeps unseen devices offline with last known measurements/timestamps, and preserves the supported protocol. Failed previews retain earlier readings.
- Per-account browser cache keeps candidates across route changes and reloads; cached devices start marked unavailable until another successful read. Storage failures do not block discovery. Registered candidates expose Edit; offline status never disables Add/Edit.
- Browser regression on isolated data: successful read, failed reread, empty scan, page reload, offline Add, offline Edit all passed. Modal/draft remained intact during the five-second sensor poll. No JavaScript errors; primary data untouched. QA server stopped.
- Four focused regressions first failed against prior behavior, then passed; frontend full suite 17 passed, ESLint and strict TypeScript/production build passed. Backend unchanged.

## Collector retry, reassignment and live availability

- Root cause of 0/2 after assignment: readings from the previous room were correctly excluded, but the next collection still waited for the normal 900-second interval. Room/address changes now make the sensor due immediately, respecting retry cooldowns.
- BLE reads use three attempts, backoff sleeps of 1 and 2 seconds, and a five-second discovery refresh before retry attempts. The Bluetooth lock is released during backoff and between sensors so UI discovery can proceed. Confirmed failures schedule a new cycle after 30 seconds independently of the normal sampling interval.
- Fresh measurements remain available during initial retries; only an exhausted cycle confirms offline. Confirmed offline state remains until a successful read, including across restarts. Waiting/reading/retrying have explicit UI labels. Time-based staleness and room attribution checks still apply.
- Successful readings are cached in SQLite config alongside sensor address/room attribution. Restart restores real cached readings; it does not fabricate a fresh timestamp. Preview of an already registered sensor now publishes/persists a genuine sample; unregistered previews remain transient.
- Removed the redundant floorplan link from the dashboard status footer. Initial empty-plan action and primary navigation remain.
- Actual native collector read Ložnice 20.8 C / 51% RH and Obývák 23.1 C / 49% RH, persisted both in InfluxDB, and restored both as available after an additional application restart. Primary data, user account and assignments preserved.
- Six new backend cases cover third-attempt recovery, exhausted attempts, restart cache, room-change scheduling, cooldown scheduling independently of interval, and stable offline state through later retries. Backend full suite 53 passed, one optional integration skipped; frontend 17 passed. Ruff, ESLint and strict production build passed. Browser verified footer removal and pending labels without JavaScript errors. QA stopped; primary health 200.

## Canonical MAC catalogue and bounded parallel BLE reads

- Settings now renders one row per normalized MAC, merging registered sensors and discoveries. Saved name, ID, room and current server state take precedence. Register/edit actions use the existing sensor; no separate factory-name row is rendered. API canonicalizes MAC formatting and rejects aliases of an existing address without changing names/assignments.
- Preview requests start concurrently in the UI. Both collector and previews use bounded asynchronous BLE reads (configurable 1–10, default 10), per-address exclusion and exclusive scanning. Retry rescans are shared when a newer scan already refreshed device objects; retries/backoff and durable samples remain. New candidates show pending/reading instead of an initial false offline state.
- Browser isolation: three preview requests were active simultaneously, the saved device appeared once as Ložnice across hyphen/case MAC variants, no registration request occurred, Edit opened the saved sensor, readings/status updated consistently, mobile had no overflow and JavaScript errors were absent. QA server stopped.
- Native isolated probe found and read five real devices successfully. Post-scan elapsed 36.32 s; observed fully entered GATT client contexts peaked at one despite concurrent requests. This does not establish a universal radio limit. Actual ten-device physical concurrency remains unverified; only five physical sensors are present. Raw evidence: .logs/parallel-probe.jsonl.
- Backend tests verify ten simultaneous mocked device reads with an eleventh queued, same-MAC exclusion, scan/read exclusion, cancellation slot cleanup, and duplicate MAC registration. Backend 59 passed, one opt-in integration skipped; frontend 19 passed. Ruff, ESLint and strict production build passed. Independent focused review found one MAC-alias publication path; fixed with a failing/passing persistent-preview regression. No further important issues found. Primary restarted with concurrency 10; account/configuration retained.

## Dialog selection does not dismiss forms

Reproduced mouse-down inside sensor name input followed by mouse-up outside closing the dialog. Removed backdrop-click dismissal from sensor, alert, import and room dialogs. Backdrop pointer-down prevents losing focus, preserving Escape after an outside click. Browser verified drag/draft preservation, outside click retention, explicit Close/Cancel/Escape, all four dialogs, focus cleanup and no JavaScript errors. Frontend 19 tests passed; ESLint and final strict production build passed. QA stopped; primary data unchanged.

## Editor sensor dropdown selection

Reproduced selecting a sensor then clicking its room clearing the dropdown. Sensor choice is now independent from room editing, bound with v-model and remembered per account/floorplan in tab session storage. Room click displays its assigned sensor, retaining a chosen sensor in rooms containing multiple markers; background interactions retain the last choice. No stored floorplan is mutated by restoring UI selection. Browser verified room/background clicks, live sensor polling, save, reload, route return, second-room assigned sensor lookup and explicit clear. Room editing remains available. Frontend 19 tests, ESLint and strict build passed; browser no JavaScript errors. QA data isolated and server stopped; primary data untouched.

## Place an existing sensor into the selected room

Reproduced selecting the tiny pantry then choosing an already placed bedroom sensor switching selection back to the bedroom. The explicitly selected room now takes precedence: the existing marker is reassigned and moved to the interior center without duplication. Selecting a sensor for inspection still leaves positions unchanged. A placement button handles an already remembered sensor when its dropdown value does not change; room clicks alone never move markers.

Isolated browser regression verified pantry coordinates (0.35, 0.3), unchanged room polygons and other marker, undo/redo, save/reload, selection persistence, explicit placement of the remembered sensor and mobile overflow. No JavaScript errors. Frontend 19 tests, ESLint and strict production build passed. Evidence: .logs/pantry-placement-verification.json; executable browser regression: .logs/pantry-placement-check.cjs. Primary data unchanged.

## Larger floorplan display

Increased responsive SVG viewport height in dashboard and editor without changing floorplan coordinates, viewBox, room proportions, real units or saved data. Scoped CSS leaves import previews unchanged. Browser compared the actual pantry polygon before/after: desktop 1440×900 +32% dashboard / +22% editor; mobile 390×844 +25% / +27%. Equal SVG scale on both axes and pantry ratio 7:6 verified; pantry selection works, Save stays disabled, stored geometry unchanged, no horizontal overflow or JavaScript errors. ESLint and strict production build passed. Evidence: .logs/plan-scale-verification.json and desktop/mobile screenshots.

## Continuous heatmap with two comfort limits

Reproduced 22.9 and 23.9 °C sharing a yellow bucket when old settings were [18,22,25]. Replaced discrete buckets with RGB interpolation from cold/dry through green at the automatic midpoint to warm/humid. Values outside the configured pair saturate at the endpoint color. Legend uses the identical color stops; missing/offline rooms remain hatched. Settings now expose two temperature limits like humidity; limits always stay in °C. Defaults are [18,25] and [30,70]. Legacy persisted/API temperature triples normalize to their outer pair; reads preserve saved preferences and the next settings save persists the pair.

Backend regression first failed on two-limit acceptance and legacy preference loading; then 64 tests passed, one opt-in integration skipped. Added five frontend color regressions: nearby temperatures, interpolation, clipping, custom humidity limits, continuity and missing values. Frontend 24 tests, ESLint, strict build, Ruff lint/format passed. Isolated browser verified two controls, save/reload, distinct fills for 22.9/23.9, green midpoint, humidity interpolation, hatching, continuous legend, Fahrenheit color invariance, desktop/mobile and no JavaScript errors. Primary restarted in BLE mode; account, sensors and floorplan preserved. QA settings restored. Evidence: .logs/heatmap-verification.json and .logs/heatmap-browser-check.cjs.

## Combined temperature and humidity history

Added Temperature / Humidity / Both chart modes in History and the room detail dialog. Temperature always uses solid lines; humidity always uses dashed lines. Combined mode uses separate temperature and percent axes, metric-specific tooltip units, stable per-room colors, two statistics rows per room, and a line-style key. Changing modes replaces obsolete series/axes while retaining current time zoom. Existing weighted room aggregation, sample gaps and missing values are preserved.

Three new regressions first failed with missing chart series; final frontend 27 tests, ESLint and strict production build passed. Isolated browser inspected the actual ECharts instance and verified two axes, correct line styles/colors, mode switches without stale series/axes, retained zoom, metric-specific tooltips, dual statistics, mobile overflow, room detail and Fahrenheit. Fixed chart tooltip overflow on viewport resizing. No JavaScript errors; QA settings restored and server stopped. Primary health 200; user configuration and measurements unchanged. Evidence: .logs/combined-chart-verification.json and desktop/mobile screenshots; reproduction script .logs/combined-chart-check.cjs.
