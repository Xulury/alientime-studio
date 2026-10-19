"""eBay adapter (optional) — Sell Inventory API.

Needs business policies (fulfillment, payment, return) and a merchant location before an offer can be
published. Listings made through the API can then only be edited through the API, not Seller Hub.
The refresh token lasts about 18 months; access tokens are refreshed automatically.
Image URLs must be public (Cloudflare R2).
"""
from __future__ import annotations

import base64
import threading
import time

from app.integrations.base import IntegrationError, TestResult, http_client
from app.publish.base import AdapterResult, ChannelAdapter, ListingRef, PublishPackage

SCOPES = "https://api.ebay.com/oauth/api_scope/sell.inventory https://api.ebay.com/oauth/api_scope/sell.account"
CONDITIONS = {"unworn": "NEW_OTHER", "excellent": "USED_EXCELLENT", "very_good": "USED_VERY_GOOD",
              "good": "USED_GOOD", "fair": "USED_ACCEPTABLE"}
_lock = threading.Lock()
_token: dict[str, tuple[str, float]] = {}


class EbayAdapter(ChannelAdapter):
    name = "ebay"
    channel = "ebay"
    label = "eBay"
    required_env = ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_REFRESH_TOKEN", "EBAY_MERCHANT_LOCATION_KEY",
                    "EBAY_FULFILLMENT_POLICY_ID", "EBAY_PAYMENT_POLICY_ID", "EBAY_RETURN_POLICY_ID")
    capabilities = ("create inventory item + offer", "publish", "update", "withdraw")
    notes = ("Listings created through the API can only be edited through the API.",
             "Needs Cloudflare R2 for public image URLs.")

    @property
    def base(self) -> str:
        return "https://api.sandbox.ebay.com" if self.settings.ebay_environment == "sandbox" else "https://api.ebay.com"

    def _access_token(self) -> str:
        key = self.settings.ebay_client_id
        with _lock:
            tok = _token.get(key)
            if tok and tok[1] - time.time() > 120:
                return tok[0]
            basic = base64.b64encode(
                f"{self.settings.ebay_client_id}:{self.settings.ebay_client_secret.get_secret_value()}".encode()).decode()
            with http_client() as c:
                r = c.post(f"{self.base}/identity/v1/oauth2/token",
                           headers={"Authorization": f"Basic {basic}"},
                           data={"grant_type": "refresh_token",
                                 "refresh_token": self.settings.ebay_refresh_token.get_secret_value(), "scope": SCOPES})
            if r.status_code != 200:
                raise IntegrationError(f"eBay token refresh failed ({r.status_code}): {r.text[:200]}")
            b = r.json()
            _token[key] = (b["access_token"], time.time() + float(b.get("expires_in", 7200)))
            return b["access_token"]

    def _req(self, method: str, path: str, json_body: dict | None = None, ok=(200, 201, 204)) -> dict:
        with http_client(timeout=60) as c:
            r = c.request(method, f"{self.base}{path}", json=json_body,
                          headers={"Authorization": f"Bearer {self._access_token()}", "Content-Language": "en-US",
                                   "Accept-Language": "en-US", "Content-Type": "application/json"})
        if r.status_code not in ok:
            raise IntegrationError(f"eBay API error {r.status_code}: {r.text[:300]}", retryable=r.status_code >= 500)
        return r.json() if r.content else {}

    def test(self) -> TestResult:
        d = self._req("GET", f"/sell/inventory/v1/location/{self.settings.ebay_merchant_location_key}")
        return TestResult(True, f"eBay connected; merchant location '{d.get('name') or self.settings.ebay_merchant_location_key}' found.")

    def _item_body(self, pkg: PublishPackage) -> dict:
        if not pkg.public_image_urls:
            raise IntegrationError("eBay needs public image URLs; configure Cloudflare R2.")
        f = pkg.facts
        aspects = {"Brand": [f.get("brand")], "Model": [f.get("model")]}
        if f.get("reference"):
            aspects["Reference Number"] = [f["reference"]]
        if f.get("case_material"):
            aspects["Case Material"] = [f["case_material"]]
        return {
            "availability": {"shipToLocationAvailability": {"quantity": 1}},
            "condition": CONDITIONS.get(f.get("condition"), "USED_EXCELLENT"),
            "conditionDescription": (pkg.sections.get("condition") or "")[:1000],
            "product": {"title": pkg.title[:80], "description": pkg.text[:4000], "aspects": aspects,
                        "imageUrls": pkg.public_image_urls[:24]},
        }

    def _offer_body(self, pkg: PublishPackage) -> dict:
        if pkg.price_usd is None:
            raise IntegrationError("eBay needs the USD price.")
        s = self.settings
        return {
            "sku": pkg.sku, "marketplaceId": s.ebay_marketplace_id, "format": "FIXED_PRICE", "availableQuantity": 1,
            "categoryId": s.ebay_category_id, "listingDescription": pkg.text[:4000],
            "listingPolicies": {"fulfillmentPolicyId": s.ebay_fulfillment_policy_id,
                                "paymentPolicyId": s.ebay_payment_policy_id,
                                "returnPolicyId": s.ebay_return_policy_id},
            "pricingSummary": {"price": {"value": f"{float(pkg.price_usd):.2f}", "currency": "USD"}},
            "merchantLocationKey": s.ebay_merchant_location_key,
        }

    def create_listing(self, pkg: PublishPackage) -> AdapterResult:
        self._req("PUT", f"/sell/inventory/v1/inventory_item/{pkg.sku}", self._item_body(pkg))
        existing = self._req("GET", f"/sell/inventory/v1/offer?sku={pkg.sku}", ok=(200, 404))
        offers = existing.get("offers") or []
        if offers:
            offer_id = offers[0]["offerId"]
            self._req("PUT", f"/sell/inventory/v1/offer/{offer_id}", self._offer_body(pkg))
        else:
            offer_id = self._req("POST", "/sell/inventory/v1/offer", self._offer_body(pkg))["offerId"]
        return AdapterResult(offer_id, None, "draft", "eBay inventory item and offer created.", {"offer_id": offer_id})

    def publish(self, ref: ListingRef) -> AdapterResult:
        d = self._req("POST", f"/sell/inventory/v1/offer/{ref.external_id}/publish")
        listing_id = d.get("listingId")
        domain = "sandbox.ebay.com" if self.settings.ebay_environment == "sandbox" else "ebay.com"
        return AdapterResult(ref.external_id, f"https://www.{domain}/itm/{listing_id}" if listing_id else None, "live",
                             "Live on eBay.", {"listing_id": listing_id})

    def update_listing(self, ref: ListingRef, pkg: PublishPackage) -> AdapterResult:
        self._req("PUT", f"/sell/inventory/v1/inventory_item/{pkg.sku}", self._item_body(pkg))
        self._req("PUT", f"/sell/inventory/v1/offer/{ref.external_id}", self._offer_body(pkg))
        return AdapterResult(ref.external_id, ref.external_url, "live", "eBay listing updated.")

    def withdraw(self, ref: ListingRef, reason: str) -> AdapterResult:
        self._req("POST", f"/sell/inventory/v1/offer/{ref.external_id}/withdraw")
        return AdapterResult(ref.external_id, ref.external_url, "sold" if reason == "sold" else "withdrawn",
                             "eBay offer withdrawn.")

    def mark_reserved(self, ref: ListingRef) -> AdapterResult:
        self._req("POST", f"/sell/inventory/v1/offer/{ref.external_id}/withdraw")
        return AdapterResult(ref.external_id, ref.external_url, "reserved", "eBay offer withdrawn while reserved.")

    def mark_available(self, ref: ListingRef) -> AdapterResult:
        return self.publish(ref)

    def check_status(self, ref: ListingRef) -> AdapterResult:
        d = self._req("GET", f"/sell/inventory/v1/offer/{ref.external_id}")
        status = d.get("status", "")
        return AdapterResult(ref.external_id, ref.external_url, "live" if status == "PUBLISHED" else "draft",
                             f"eBay offer status: {status}")
