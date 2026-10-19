"""Cloudflare R2 (S3-compatible): public URLs for approved, sanitised final images only.

Instagram's API fetches images from a public URL, and the Chrono24 feed and eBay need image URLs too.
Only approved finals are uploaded, under hard-to-guess paths. Originals are never uploaded.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from app.integrations.base import Integration, IntegrationError, TestResult


class CloudflareR2(Integration):
    name = "cloudflare_r2"
    label = "Cloudflare R2 (public images)"
    kind = "storage"
    required_env = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL", "CLOUDFLARE_ACCOUNT_ID")
    capabilities = ("upload approved finals", "delete on withdraw", "host Chrono24 feed")
    notes = ("Use a token limited to this one bucket.",)

    def _client(self):
        try:
            import boto3  # optional dependency (requirements-integrations.txt)
        except ImportError as e:
            raise IntegrationError("Install requirements-integrations.txt to use Cloudflare R2.") from e
        s = self.settings
        endpoint = s.r2_endpoint_url or f"https://{s.cloudflare_account_id}.r2.cloudflarestorage.com"
        return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=s.r2_access_key_id,
                            aws_secret_access_key=s.r2_secret_access_key.get_secret_value(), region_name="auto")

    def test(self) -> TestResult:
        self._client().head_bucket(Bucket=self.settings.r2_bucket)
        return TestResult(True, f"Bucket {self.settings.r2_bucket} is reachable.")

    def public_url(self, key: str) -> str:
        return self.settings.r2_public_base_url.rstrip("/") + "/" + key

    def upload_file(self, path: Path, key: str, content_type: str = "image/jpeg", cache_seconds: int = 3600) -> str:
        if not self.is_configured():
            raise IntegrationError("Cloudflare R2 is not configured; public image URLs are unavailable.")
        self._client().upload_file(str(path), self.settings.r2_bucket, key,
                                   ExtraArgs={"ContentType": content_type, "CacheControl": f"public, max-age={cache_seconds}"})
        return self.public_url(key)

    def upload_images(self, sku: str, paths: list[Path]) -> tuple[list[str], list[str]]:
        """Upload finals under a random prefix. Returns (urls, keys)."""
        prefix = f"l/{secrets.token_urlsafe(18)}"
        urls, keys = [], []
        for i, p in enumerate(paths, 1):
            key = f"{prefix}/{sku}_{i:02d}.jpg"
            urls.append(self.upload_file(p, key))
            keys.append(key)
        return urls, keys

    def delete_keys(self, keys: list[str]) -> None:
        if not keys or not self.is_configured():
            return
        self._client().delete_objects(Bucket=self.settings.r2_bucket,
                                      Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True})
