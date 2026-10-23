# BLE connection strategy experiment, 2026-10-23

Standalone measurement tool: [scripts/ble_benchmark.py](../../scripts/ble_benchmark.py).
It uses the unmodified SensoGrid LTDriver and BLERadio, and never opens the
application database or writes InfluxDB. Sensor names/addresses are exported
read-only before stopping the production collector.

Approved profiles, each 600 seconds:

| Profile | Maximum connections | Initial connection stagger |
| --- | --- | --- |
| A | 1 | 0 |
| B | 2 | 0 |
| C | 5 | 0 |
| D | 5 | 500 ms per position |

Common controls: Bleak 3.0.2, matching driver source hashes, three attempts,
1/2-second retry delays, 15-second initial scan, 5-second retry scan,
12-second measurement timeout plus the existing driver connection budget.
Scanning is exclusive of connections. Order uses the same seeded shuffle for
each minute across profiles. A fresh driver/cache/radio coordinator is created
for each profile; 20 seconds of idle time separate profiles. BlueZ is not reset
between profiles.

The offered load is one requested sample per sensor per minute, with fixed
start times. Overdue whole slots are explicitly marked missed instead of
building a queue. The production collector currently schedules relative to
successful completion and waits on the batch, so these results must not be
interpreted as a direct before/after throughput comparison with its night logs.

Each ten-minute profile plans 10 samples per sensor (50 overall). Deadline
cancellation is recorded separately from an exhausted sensor failure. Delivery
percentage includes missed and censored opportunities. First-attempt success
uses completed first read calls; successful retry cycles are reported
separately. On-time delivery requires completion within 60 seconds of the
scheduled start, including scan/queue/disconnect overhead.

The raw journal records every attempt, scan, cycle, exact exception/traceback,
queue/read/total duration and the decoded sample. RSSI comes from the most
recent advertisement, not from a guaranteed measurement of the connection.
Invalid placeholder RSSI values (-127 etc.) are excluded from median RSSI.

## Safety and service state

On HomeServer, only sensogrid-app-1 is stopped; InfluxDB and unrelated
applications remain running. run_debian.py supervises the standalone,
unprivileged, network-disabled benchmark container using the exact production
image. It keeps production stopped during the later Windows experiment so the
two controllers never compete for the same sensors. It restores SensoGrid when
the host release file is created, on an error, or after 110 minutes. It remains
running after SSH disconnects. This is not a recurring watchdog or a permanent
change to system services.

Host-specific workspace:
 /home/marek/sensogrid-ble-benchmark-20261023

- input/: script and sensor list.
- artifacts/debian/: raw journals, per-profile summaries, CSV, metadata.
- supervisor.jsonl / benchmark.log: lifecycle and diagnostic stdout.
- host-metadata.txt / bluez-before.txt / bluez-after-linux.txt: environment.
- release: create only once the Windows experiment is no longer using sensors.

Emergency controlled restoration (stop the owned test first):

```sh
docker stop --timeout 20 sensogrid-ble-benchmark-20261023
docker start sensogrid-app-1
```

Normal restoration: create the release file in the workspace and let the
supervisor restore the app. Verify fresh samples from all five sensors, not
only HTTP/container health.

## Reproduce one host

Stop all SensoGrid collectors using these devices first. Pass an exported JSON
list with name and address fields. Use a new output directory:

```sh
python scripts/ble_benchmark.py --sensors /path/sensors.json \
  --output /path/new-results --duration 600 --interval 60 --attempts 3
```

Use the same command on Windows with its native Python/Bleak installation.
Do not overlap runs on the two machines. Sensor positions should remain fixed;
controller position, OS stack, other radio activity and signal strength are
uncontrolled differences unless explicitly matched.

## Interpretation

Ten-minute runs are a pilot: at most ten first-attempt observations per sensor
per profile. Wilson intervals are reported as descriptive bounds; correlated
radio conditions mean they do not establish independence or statistical
significance. Rank delivery/timeliness and worst-sensor behavior before raw
attempt percentages. Close results require a longer, counterbalanced repeat.
Changing retry count is a separate experiment after concurrency selection.

Raw data and working notes are under the ignored .logs/ble-benchmark-20261023
directory in the main repository. Final report: [Debian and Windows results](../../docs/ble-benchmark-2026-10-23.md).
Per-sensor machine-readable results: [CSV](results-2026-10-23.csv).

The measured script is preserved as .logs/ble-benchmark-20261023/benchmark-used.py.
After both runs, the future runner was fixed to drain cancelled sibling tasks
before closing the journal. Two started cycles in Linux C/D were reclassified
from missed to censored in summary-corrected.json; raw journals remain unchanged.
Success and on-time counts are unchanged. The experiments were not rerun after
this diagnostic fix. C/D have cleanup limitations; Linux D also contains a
confirmed BlueZ SIGSEGV. The report describes these limitations and the sensor
that disappeared before the Windows runs.
