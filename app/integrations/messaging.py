"""Telegram (optional notifications; Hermes owns the conversation) and WhatsApp Cloud API (optional intake)."""
from __future__ import annotations

import hashlib
import hmac

from app.integrations.base import Integration, IntegrationError, TestResult, http_client


class Telegram(Integration):
    name = "telegram"
    label = "Telegram bot"
    kind = "messaging"
    required_env = ("TELEGRAM_BOT_TOKEN",)
    capabilities = ("notifications to the allow-listed chat",)
    notes = ("Hermes runs the conversation; the studio only sends notifications.",
             "TELEGRAM_ADMIN_USERS lists who may approve, publish and mark sold through Hermes.")

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.settings.telegram_bot_token.get_secret_value()}/{method}"

    def test(self) -> TestResult:
        with http_client() as c:
            r = c.get(self._url("getMe"))
        d = r.json()
        if not d.get("ok"):
            return TestResult(False, f"Telegram rejected the token: {d.get('description')}")
        return TestResult(True, f"Bot @{d['result'].get('username')} is reachable.")

    def notify(self, text: str) -> bool:
        chat = self.settings.telegram_notify_chat_id
        if not self.is_configured() or not chat:
            return False
        with http_client() as c:
            r = c.post(self._url("sendMessage"), json={"chat_id": chat, "text": text[:4000],
                                                       "disable_web_page_preview": True})
        if r.status_code >= 400:
            raise IntegrationError(f"Telegram sendMessage failed ({r.status_code})", retryable=r.status_code >= 500)
        return True


class WhatsAppCloud(Integration):
    name = "whatsapp"
    label = "WhatsApp Cloud API"
    kind = "messaging"
    required_env = ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN")
    capabilities = ("consignor photo intake (webhook)",)
    notes = ("Use a number that is not your WhatsApp Business app line.",
             "Dealer group posting is not available through the API; those stay draft packs.")

    def test(self) -> TestResult:
        with http_client() as c:
            r = c.get(f"https://graph.facebook.com/{self.settings.meta_graph_version}/{self.settings.whatsapp_phone_number_id}",
                      params={"fields": "display_phone_number,verified_name",
                              "access_token": self.settings.whatsapp_access_token.get_secret_value()})
        d = r.json()
        if r.status_code >= 400:
            return TestResult(False, f"WhatsApp API error: {d.get('error', {}).get('message', r.status_code)}")
        return TestResult(True, f"WhatsApp number {d.get('display_phone_number')} ({d.get('verified_name')}) reachable.")

    def verify_signature(self, body: bytes, header: str | None) -> bool:
        if not header or not header.startswith("sha256=") or not self.settings.whatsapp_app_secret:
            return False
        expected = hmac.new(self.settings.whatsapp_app_secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header[7:])

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        tok = self.settings.whatsapp_access_token.get_secret_value()
        with http_client(timeout=60) as c:
            meta = c.get(f"https://graph.facebook.com/{self.settings.meta_graph_version}/{media_id}",
                         params={"access_token": tok}).json()
            if "url" not in meta:
                raise IntegrationError("WhatsApp media lookup failed.")
            r = c.get(meta["url"], headers={"Authorization": f"Bearer {tok}"})
        if r.status_code >= 400:
            raise IntegrationError("WhatsApp media download failed.", retryable=r.status_code >= 500)
        return r.content, meta.get("mime_type", "image/jpeg")
