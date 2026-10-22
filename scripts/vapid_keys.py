"""Create optional VAPID identity; update local .env without displaying secrets."""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

root = Path(__file__).resolve().parents[1]
folder = root / ".secrets"
env = root / ".env"
if not env.exists():
    raise SystemExit("Run scripts/bootstrap.py first.")
folder.mkdir(mode=0o700, exist_ok=True)
private, public = folder / "vapid-private.pem", folder / "vapid-public.txt"
if private.exists() or public.exists():
    raise SystemExit("VAPID identity exists; refusing to invalidate browser subscriptions.")
key = ec.generate_private_key(ec.SECP256R1())
private.write_bytes(
    key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
)


def encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


private_raw = encode(key.private_numbers().private_value.to_bytes(32, "big"))
public_raw = encode(
    key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
)
public.write_text(public_raw, encoding="utf-8")
lines = env.read_text(encoding="utf-8").splitlines()
values = {"SENSOGRID_VAPID_PRIVATE_KEY": private_raw, "SENSOGRID_VAPID_PUBLIC_KEY": public_raw}
for name, value in values.items():
    if any(line.startswith(name + "=") for line in lines):
        lines = [name + "=" + value if line.startswith(name + "=") else line for line in lines]
    else:
        lines.append(name + "=" + value)
env.write_text("\n".join(lines) + "\n", encoding="utf-8")
if os.name != "nt":
    private.chmod(0o600)
    env.chmod(0o600)
print("VAPID identity saved in .secrets/; .env updated. Credentials not printed.")
