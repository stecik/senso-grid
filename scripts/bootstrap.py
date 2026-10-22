"""Create local deployment secrets without printing credentials. Never overwrites."""

import json
import os
import secrets
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = root / ".env"
secret_dir = root / ".secrets"
token_file = secret_dir / "influxdb-admin.json"
if env.exists() or token_file.exists():
    sys.exit("Configuration already exists; refusing to replace credentials.")
secret_dir.mkdir(mode=0o700, exist_ok=True)
token = "apiv3_" + secrets.token_urlsafe(48)
token_file.write_text(
    json.dumps({"token": token, "name": "sensogrid", "expiry_millis": None}), encoding="utf-8"
)
# Parent directory is private; mounted secret must be readable by the DB user.
if os.name != "nt":
    token_file.chmod(0o644)
template = (root / ".env.example").read_text(encoding="utf-8")
env.write_text(
    template.replace("SENSOGRID_INFLUX_TOKEN=\n", "SENSOGRID_INFLUX_TOKEN=" + token + "\n"),
    encoding="utf-8",
)
if os.name != "nt":
    env.chmod(0o600)
print("Created .env and private .secrets/influxdb-admin.json. Credentials not printed.")
