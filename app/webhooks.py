"""Outbound webhook delivery with retries (in-memory, per-instance).

Delivery semantics:
- 1st attempt immediately in a daemon thread
- on failure (network error or HTTP >= 400) → retry after 60s, 300s, 900s
- after 3 failed retries → give up, set last_error on the webhook row

For multi-instance deploys swap with a queue (Redis/Celery/RQ).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

import urllib.request
from sqlalchemy import select

from .database import session_scope
from .models import Webhook

log = logging.getLogger(__name__)

RETRY_DELAYS_S = (60, 300, 900)  # 1min, 5min, 15min


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _attempt(webhook_id: int, payload: dict[str, Any]) -> bool:
    """One attempt. Returns True on success (2xx), False otherwise."""
    with session_scope() as db:
        wh = db.get(Webhook, webhook_id)
        if not wh or not wh.enabled:
            return True  # treat disabled as "done", no retry
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            wh.url, data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "dmarc-aggregator/1.0",
                "X-DMARC-Signature": _sign(wh.secret, body),
                "X-DMARC-Event": payload.get("event", ""),
            },
            method="POST",
        )
        success = False
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                wh.last_status = resp.status
                if 200 <= resp.status < 300:
                    wh.last_error = None
                    success = True
                else:
                    wh.last_error = f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            wh.last_status = e.code
            wh.last_error = f"HTTP {e.code}"[:1000]
        except Exception as e:  # noqa: BLE001
            wh.last_status = 0
            wh.last_error = str(e)[:1000]
            log.warning("Webhook %s failed: %s", wh.id, e)
        finally:
            wh.last_called_at = datetime.now(timezone.utc)
        return success


def _deliver_with_retries(webhook_id: int, payload: dict[str, Any]) -> None:
    if _attempt(webhook_id, payload):
        return
    for i, delay in enumerate(RETRY_DELAYS_S, start=1):
        threading.Event().wait(delay)
        log.info("Webhook %s retry %s/%s after %ss", webhook_id, i, len(RETRY_DELAYS_S), delay)
        if _attempt(webhook_id, payload):
            return
    log.warning("Webhook %s gave up after %s retries", webhook_id, len(RETRY_DELAYS_S))


def emit(tenant_id: int, event: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget webhook emit with background retries. One thread per matching hook."""
    with session_scope() as db:
        ids = db.execute(
            select(Webhook.id).where(
                Webhook.tenant_id == tenant_id, Webhook.enabled.is_(True),
            )
        ).scalars().all()

    full = {"event": event, "tenant_id": tenant_id, **payload}
    for wid in ids:
        threading.Thread(target=_deliver_with_retries, args=(wid, full), daemon=True).start()
