"""Meta adapters: Instagram (content publishing API) and the Facebook Page (Graph API).

Instagram: professional account only; JPEG images fetched from public URLs (Cloudflare R2); a carousel
holds up to 10 items and counts as one post; API-published posts are rate limited per 24 hours.
Flow: one container per image (is_carousel_item) → CAROUSEL container with caption → poll status_code →
media_publish → permalink. The API cannot delete or re-caption a published post, so reserved/sold create
a manual task instead.

Facebook Page: photos uploaded unpublished, then one feed post with attached_media; the post text can be
edited and the post deleted through the API.
"""
from __future__ import annotations

import json
import time

from app.integrations.base import IntegrationError, TestResult, UnsupportedOperation, http_client
from app.publish.base import AdapterResult, ChannelAdapter, ListingRef, PublishPackage


class _GraphMixin:
    settings: object

    @property
    def graph(self) -> str:
        return f"https://graph.facebook.com/{self.settings.meta_graph_version}"

    def _system_token(self) -> str:
        return self.settings.meta_system_user_token.get_secret_value()

    def _call(self, method: str, path: str, token: str, **params) -> dict:
        with http_client(timeout=60) as c:
            clean = {k: v for k, v in params.items() if v is not None}
            if method in ("GET", "DELETE"):
                r = c.request(method, f"{self.graph}/{path.lstrip('/')}", params={**clean, "access_token": token})
            else:
                r = c.request(method, f"{self.graph}/{path.lstrip('/')}", params={"access_token": token}, data=clean)
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text[:300]}
        if r.status_code >= 400 or "error" in body:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            code = err.get("code")
            retry = r.status_code >= 500 or code in (1, 2, 4, 17, 32, 613)
            raise IntegrationError(f"Meta API error {r.status_code}: {err.get('message', body)}"[:400], retryable=retry)
        return body


class InstagramAdapter(_GraphMixin, ChannelAdapter):
    name = "instagram"
    channel = "instagram"
    label = "Instagram"
    required_env = ("META_SYSTEM_USER_TOKEN", "IG_USER_ID_ALIENTIME_SG")
    capabilities = ("publish carousel (≤ 10 images)",)
    notes = ("Needs Cloudflare R2 for public image URLs.",
             "Published posts cannot be edited or deleted through the API: reserved/sold create a manual task.")
    poll_seconds = 4.0
    poll_max = 30

    def accounts(self) -> list[str]:
        ids = [self.settings.ig_user_id_alientime_sg, self.settings.ig_user_id_official]
        return [i for i in ids if i]

    def test(self) -> TestResult:
        details = {}
        for ig in self.accounts():
            d = self._call("GET", ig, self._system_token(), fields="username,account_type")
            details[ig] = d.get("username")
        return TestResult(True, "Instagram accounts reachable: " + ", ".join(str(v) for v in details.values()), details)

    def _wait(self, container: str, token: str) -> None:
        for _ in range(self.poll_max):
            d = self._call("GET", container, token, fields="status_code")
            status = d.get("status_code")
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                raise IntegrationError(f"Instagram could not process the media ({status}).")
            time.sleep(self.poll_seconds)
        raise IntegrationError("Instagram is still processing the media; will retry.", retryable=True)

    def _publish_to(self, ig: str, pkg: PublishPackage, token: str) -> dict:
        urls = pkg.public_image_urls[:10]
        if not urls:
            raise IntegrationError("Instagram needs public image URLs; configure Cloudflare R2.")
        caption = pkg.text
        if len(urls) == 1:
            container = self._call("POST", f"{ig}/media", token, image_url=urls[0], caption=caption)["id"]
        else:
            children = [self._call("POST", f"{ig}/media", token, image_url=u, is_carousel_item="true")["id"]
                        for u in urls]
            for ch in children:
                self._wait(ch, token)
            container = self._call("POST", f"{ig}/media", token, media_type="CAROUSEL",
                                   children=",".join(children), caption=caption)["id"]
        self._wait(container, token)
        media_id = self._call("POST", f"{ig}/media_publish", token, creation_id=container)["id"]
        link = self._call("GET", media_id, token, fields="permalink").get("permalink")
        return {"account": ig, "media_id": media_id, "permalink": link}

    def publish_new(self, pkg: PublishPackage) -> AdapterResult:
        token = self._system_token()
        posts = [self._publish_to(ig, pkg, token) for ig in self.accounts()]
        first = posts[0]
        return AdapterResult(first["media_id"], first["permalink"], "live",
                             f"Posted to {len(posts)} Instagram account(s).", {"posts": posts})

    def create_listing(self, pkg: PublishPackage) -> AdapterResult:
        return self.publish_new(pkg)


class FacebookPageAdapter(_GraphMixin, ChannelAdapter):
    name = "facebook_page"
    channel = "facebook_page"
    label = "Facebook Page"
    required_env = ("META_SYSTEM_USER_TOKEN", "FB_PAGE_ID")
    capabilities = ("publish photo post", "edit post text", "delete post")
    notes = ("Your own Page only.",)

    def _page_token(self) -> str:
        d = self._call("GET", self.settings.fb_page_id, self._system_token(), fields="access_token,name")
        tok = d.get("access_token")
        if not tok:
            raise IntegrationError("The system user has no access token for this Page (needs pages_manage_posts).")
        return tok

    def test(self) -> TestResult:
        d = self._call("GET", self.settings.fb_page_id, self._system_token(), fields="name,access_token")
        if not d.get("access_token"):
            return TestResult(False, f"Page '{d.get('name')}' found, but no Page token: grant pages_manage_posts.")
        return TestResult(True, f"Connected to the Page '{d.get('name')}'.")

    def publish_new(self, pkg: PublishPackage) -> AdapterResult:
        token = self._page_token()
        page = self.settings.fb_page_id
        media_ids = []
        for i, path in enumerate(pkg.images[:10]):
            if pkg.public_image_urls and i < len(pkg.public_image_urls):
                d = self._call("POST", f"{page}/photos", token, url=pkg.public_image_urls[i], published="false")
            else:
                with http_client(timeout=120) as c, open(path, "rb") as fh:
                    r = c.post(f"{self.graph}/{page}/photos", data={"published": "false", "access_token": token},
                               files={"source": (path.name, fh, "image/jpeg")})
                d = r.json()
                if r.status_code >= 400 or "error" in d:
                    raise IntegrationError(f"Facebook photo upload failed: {d.get('error', {}).get('message', r.text[:200])}",
                                           retryable=r.status_code >= 500)
            media_ids.append(d["id"])
        params = {"message": pkg.text}
        for i, mid in enumerate(media_ids):
            params[f"attached_media[{i}]"] = json.dumps({"media_fbid": mid})
        post = self._call("POST", f"{page}/feed", token, **params)
        link = self._call("GET", post["id"], token, fields="permalink_url").get("permalink_url")
        return AdapterResult(post["id"], link, "live", "Posted to the Facebook Page.", {"photos": media_ids})

    def create_listing(self, pkg: PublishPackage) -> AdapterResult:
        return self.publish_new(pkg)

    def update_listing(self, ref: ListingRef, pkg: PublishPackage) -> AdapterResult:
        self._call("POST", ref.external_id, self._page_token(), message=pkg.text)
        return AdapterResult(ref.external_id, ref.external_url, "live", "Facebook post text updated.")

    def _edit_prefix(self, ref: ListingRef, prefix: str) -> None:
        token = self._page_token()
        cur = self._call("GET", ref.external_id, token, fields="message").get("message", "")
        if not cur.startswith(prefix):
            self._call("POST", ref.external_id, token, message=f"{prefix}\n\n{cur}")

    def mark_reserved(self, ref: ListingRef) -> AdapterResult:
        self._edit_prefix(ref, "RESERVED")
        return AdapterResult(ref.external_id, ref.external_url, "reserved", "Post marked RESERVED.")

    def mark_available(self, ref: ListingRef) -> AdapterResult:
        token = self._page_token()
        cur = self._call("GET", ref.external_id, token, fields="message").get("message", "")
        for p in ("RESERVED\n\n",):
            if cur.startswith(p):
                self._call("POST", ref.external_id, token, message=cur[len(p):])
        return AdapterResult(ref.external_id, ref.external_url, "live", "Post available again.")

    def withdraw(self, ref: ListingRef, reason: str) -> AdapterResult:
        if reason == "sold":
            self._edit_prefix(ref, "SOLD")
            return AdapterResult(ref.external_id, ref.external_url, "sold", "Post marked SOLD.")
        self._call("DELETE", ref.external_id, self._page_token())
        return AdapterResult(ref.external_id, None, "withdrawn", "Post deleted from the Page.")

    def check_status(self, ref: ListingRef) -> AdapterResult:
        d = self._call("GET", ref.external_id, self._page_token(), fields="permalink_url,is_published")
        return AdapterResult(ref.external_id, d.get("permalink_url"), "live" if d.get("is_published", True) else "draft",
                             "Post exists.")


__all__ = ["InstagramAdapter", "FacebookPageAdapter", "UnsupportedOperation"]
