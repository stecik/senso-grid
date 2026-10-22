"""Optional browser push. Monitoring never depends on external delivery."""

import asyncio
import ipaddress
import json
import socket
from urllib.parse import urlsplit

import requests

PUSH_HOSTS = {
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
}


def validate_endpoint(endpoint: str, resolve: bool = True) -> str:
    try:
        url = urlsplit(endpoint)
        host = (url.hostname or "").lower()
        allowed = (
            host in PUSH_HOSTS
            or host.endswith(".push.services.mozilla.com")
            or host.endswith(".notify.windows.com")
            or host.endswith(".push.apple.com")
        )
        if (
            url.scheme != "https"
            or not allowed
            or url.username
            or url.password
            or url.port not in (None, 443)
            or not url.path
            or url.fragment
        ):
            raise ValueError("Unsupported push endpoint")
        if resolve:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses or any(
                not ipaddress.ip_address(item[4][0]).is_global for item in addresses
            ):
                raise ValueError("Push endpoint must resolve to public addresses")
    except (OSError, ValueError) as exc:
        raise ValueError("Invalid or unavailable push endpoint") from exc
    return endpoint


class NoRedirectSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False

    def request(self, *args, **kwargs):
        kwargs["allow_redirects"] = False
        response = super().request(*args, **kwargs)
        if response.is_redirect:
            raise ValueError("Push redirects are forbidden")
        return response


class PushService:
    def __init__(self, settings, db):
        self.settings, self.db = settings, db

    @property
    def available(self) -> bool:
        return bool(self.settings.vapid_private_key and self.settings.vapid_public_key)

    def send(self, subscription: dict, payload: dict) -> bool:
        from pywebpush import WebPushException, webpush

        validate_endpoint(subscription["endpoint"])
        try:
            with NoRedirectSession() as session:
                webpush(
                    subscription_info={
                        "endpoint": subscription["endpoint"],
                        "keys": subscription["keys"],
                    },
                    data=json.dumps(payload),
                    vapid_private_key=self.settings.vapid_private_key,
                    vapid_claims={"sub": self.settings.vapid_subject},
                    timeout=8,
                    ttl=3600,
                    requests_session=session,
                )
            return True
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                self.db.delete_subscription(subscription["endpoint"])
            return False
        except (requests.RequestException, ValueError):
            return False

    async def dispatch(self, payload: dict) -> dict[str, int]:
        if not self.available:
            return {"sent": 0, "failed": 0}
        sent = failed = 0
        for subscription in self.db.subscriptions():
            try:
                success = await asyncio.to_thread(self.send, subscription, payload)
            except Exception:
                success = False
            if success:
                sent += 1
            else:
                failed += 1
        return {"sent": sent, "failed": failed}
