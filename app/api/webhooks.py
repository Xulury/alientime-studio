"""WhatsApp Cloud API webhook (optional consignor photo intake).

Disabled unless the WhatsApp variables are configured. The verification handshake checks the verify
token; incoming messages must carry a valid X-Hub-Signature-256 from the app secret. Images are saved
to the local inbox (folder 'whatsapp-<sender>') for a person to assign — never straight into a listing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse, Response

from app.config import get_settings
from app.core.security import constant_time_equals
from app.integrations.messaging import WhatsAppCloud

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)


@router.get("/whatsapp")
def verify(mode: str = Query(alias="hub.mode", default=""), token: str = Query(alias="hub.verify_token", default=""),
           challenge: str = Query(alias="hub.challenge", default="")):
    wa = WhatsAppCloud()
    if not wa.is_configured():
        return Response(status_code=404)
    expected = get_settings().whatsapp_verify_token.get_secret_value()
    if mode == "subscribe" and token and constant_time_equals(token, expected):
        return PlainTextResponse(challenge)
    return Response(status_code=403)


@router.post("/whatsapp")
async def receive(request: Request):
    wa = WhatsAppCloud()
    if not wa.is_configured():
        return Response(status_code=404)
    body = await request.body()
    if not wa.verify_signature(body, request.headers.get("x-hub-signature-256")):
        return Response(status_code=403)
    try:
        payload = json.loads(body)
    except ValueError:
        return Response(status_code=400)
    saved = 0
    inbox = get_settings().inbox_dir
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in (change.get("value") or {}).get("messages", []) or []:
                if msg.get("type") != "image":
                    continue
                sender = "".join(c for c in str(msg.get("from", "unknown")) if c.isdigit())[-6:] or "unknown"
                try:
                    data, mime = wa.download_media(msg["image"]["id"])
                except Exception as e:  # noqa: BLE001
                    log.warning("whatsapp media download failed: %s", e)
                    continue
                folder = inbox / f"whatsapp-{sender}"
                folder.mkdir(parents=True, exist_ok=True)
                ext = "png" if "png" in mime else "webp" if "webp" in mime else "jpg"
                (folder / f"IMG-{datetime.now():%Y%m%d}-WA{msg.get('id', '')[-8:]}.{ext}").write_bytes(data)
                saved += 1
    return {"saved": saved}
