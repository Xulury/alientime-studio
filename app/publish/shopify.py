"""Shopify adapter — Admin GraphQL API with a Dev Dashboard app.

Tokens come from the client-credentials grant (POST /admin/oauth/access_token) and expire after about
24 hours (`expires_in` 86399); the adapter caches and refreshes them itself. App and store must belong
to the same Shopify organization. Scopes: write_products, read_products, write_inventory, read_locations,
write_publications.

Flow: productSet creates the product as DRAFT with images, then publish sets it ACTIVE and publishes it
to the Online Store; sold archives it; reserved hides it (DRAFT) until it is available again.
Images: public R2 URLs when configured, otherwise Shopify staged uploads.
"""
from __future__ import annotations

import html
import threading
import time
from decimal import Decimal

from app.integrations.base import IntegrationError, TestResult, http_client
from app.publish.base import AdapterResult, ChannelAdapter, ListingRef, PublishPackage

_token_lock = threading.Lock()
_token_cache: dict[str, tuple[str, float]] = {}


def _html_description(pkg: PublishPackage) -> str:
    paras = [p.strip() for p in pkg.text.split("\n\n") if p.strip()]
    out = []
    for p in paras:
        lines = p.split("\n")
        if all(l.startswith(("- ", "• ")) for l in lines):
            out.append("<ul>" + "".join(f"<li>{html.escape(l[2:])}</li>" for l in lines) + "</ul>")
        else:
            out.append("<p>" + "<br>".join(html.escape(l) for l in lines) + "</p>")
    return "\n".join(out)


class ShopifyAdapter(ChannelAdapter):
    name = "shopify"
    channel = "shopify"
    label = "Shopify"
    required_env = ("SHOPIFY_SHOP", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET")
    capabilities = ("create draft", "publish", "update", "archive on sold", "hide while reserved")
    notes = ("Tokens refresh automatically every 24 hours.", "App and store must be in the same Shopify organization.")

    # ---- auth ------------------------------------------------------------------------------------
    @property
    def shop_domain(self) -> str:
        shop = self.settings.shopify_shop.strip()
        return shop if shop.endswith(".myshopify.com") else f"{shop}.myshopify.com"

    def _token(self, force: bool = False) -> str:
        key = self.shop_domain
        with _token_lock:
            tok = _token_cache.get(key)
            if tok and not force and tok[1] - time.time() > 300:
                return tok[0]
            with http_client() as c:
                r = c.post(f"https://{key}/admin/oauth/access_token",
                           data={"grant_type": "client_credentials", "client_id": self.settings.shopify_client_id,
                                 "client_secret": self.settings.shopify_client_secret.get_secret_value()})
            if r.status_code != 200:
                raise IntegrationError(f"Shopify token request failed ({r.status_code}): {r.text[:200]}")
            body = r.json()
            _token_cache[key] = (body["access_token"], time.time() + float(body.get("expires_in", 86399)))
            return body["access_token"]

    def gql(self, query: str, variables: dict | None = None) -> dict:
        url = f"https://{self.shop_domain}/admin/api/{self.settings.shopify_api_version}/graphql.json"
        for attempt in (0, 1):
            with http_client(timeout=60) as c:
                r = c.post(url, json={"query": query, "variables": variables or {}},
                           headers={"X-Shopify-Access-Token": self._token(force=attempt == 1)})
            if r.status_code == 401 and attempt == 0:
                continue
            if r.status_code == 429 or r.status_code >= 500:
                raise IntegrationError(f"Shopify is busy ({r.status_code}); will retry.", retryable=True)
            if r.status_code != 200:
                raise IntegrationError(f"Shopify API error {r.status_code}: {r.text[:300]}")
            data = r.json()
            if data.get("errors"):
                raise IntegrationError(f"Shopify GraphQL error: {str(data['errors'])[:300]}")
            return data["data"]
        raise IntegrationError("Shopify rejected the access token.")

    def test(self) -> TestResult:
        d = self.gql("{ shop { name myshopifyDomain } }")
        return TestResult(True, f"Connected to {d['shop']['name']}.", {"domain": d["shop"]["myshopifyDomain"]})

    # ---- media -----------------------------------------------------------------------------------
    def _staged_sources(self, pkg: PublishPackage) -> list[str]:
        inputs = [{"resource": "IMAGE", "filename": p.name, "mimeType": "image/jpeg", "httpMethod": "POST",
                   "fileSize": str(p.stat().st_size)} for p in pkg.images]
        d = self.gql("""mutation($input:[StagedUploadInput!]!){ stagedUploadsCreate(input:$input){
            stagedTargets{ url resourceUrl parameters{ name value } } userErrors{ field message } } }""",
                     {"input": inputs})
        res = d["stagedUploadsCreate"]
        if res["userErrors"]:
            raise IntegrationError(f"Shopify staged upload failed: {res['userErrors']}")
        sources = []
        for target, path in zip(res["stagedTargets"], pkg.images):
            form = {p["name"]: p["value"] for p in target["parameters"]}
            with http_client(timeout=120) as c, open(path, "rb") as fh:
                r = c.post(target["url"], data=form, files={"file": (path.name, fh, "image/jpeg")})
            if r.status_code not in (200, 201, 204):
                raise IntegrationError(f"Uploading {path.name} to Shopify failed ({r.status_code}).", retryable=True)
            sources.append(target["resourceUrl"])
        return sources

    def _product_input(self, pkg: PublishPackage, status: str) -> dict:
        price = pkg.price_sgd
        if price is None:
            raise IntegrationError("Shopify needs the SGD price.")
        sources = pkg.public_image_urls or self._staged_sources(pkg)
        f = pkg.facts
        return {
            "title": pkg.title,
            "descriptionHtml": _html_description(pkg),
            "vendor": f.get("brand"),
            "productType": "Watch",
            "status": status,
            "tags": [t for t in ("alientime", f.get("brand"), f"sku:{pkg.sku}") if t],
            "productOptions": [{"name": "Title", "values": [{"name": "Default Title"}]}],
            "variants": [{"optionValues": [{"optionName": "Title", "name": "Default Title"}],
                          "price": str(Decimal(str(price)).quantize(Decimal("0.01")))}],
            "files": [{"originalSource": s, "contentType": "IMAGE", "alt": f"{pkg.title} — image {i + 1}"}
                      for i, s in enumerate(sources)],
        }

    _SET = """mutation($input: ProductSetInput!, $identifier: ProductSetIdentifiers){
        productSet(synchronous: true, input: $input, identifier: $identifier){
          product{ id handle onlineStoreUrl status } userErrors{ field message code } } }"""

    def create_listing(self, pkg: PublishPackage) -> AdapterResult:
        d = self.gql(self._SET, {"input": self._product_input(pkg, "DRAFT"), "identifier": None})
        res = d["productSet"]
        if res["userErrors"]:
            raise IntegrationError(f"Shopify rejected the product: {res['userErrors']}")
        p = res["product"]
        return AdapterResult(p["id"], p.get("onlineStoreUrl"), "draft", "Created as a draft in Shopify.",
                             {"handle": p.get("handle")})

    def update_listing(self, ref: ListingRef, pkg: PublishPackage) -> AdapterResult:
        d = self.gql(self._SET, {"input": self._product_input(pkg, "ACTIVE"), "identifier": {"id": ref.external_id}})
        res = d["productSet"]
        if res["userErrors"]:
            raise IntegrationError(f"Shopify rejected the update: {res['userErrors']}")
        p = res["product"]
        return AdapterResult(p["id"], p.get("onlineStoreUrl") or ref.external_url, "live", "Shopify product updated.",
                             {"handle": p.get("handle")})

    def _set_status(self, product_id: str, status: str) -> dict:
        d = self.gql("""mutation($product: ProductUpdateInput!){ productUpdate(product: $product){
            product{ id status onlineStoreUrl handle } userErrors{ field message } } }""",
                     {"product": {"id": product_id, "status": status}})
        res = d["productUpdate"]
        if res["userErrors"]:
            raise IntegrationError(f"Shopify could not change status: {res['userErrors']}")
        return res["product"]

    def _online_store_publication(self) -> str | None:
        d = self.gql("{ publications(first: 20){ nodes{ id name } } }")
        for n in d["publications"]["nodes"]:
            if n["name"].lower() == "online store":
                return n["id"]
        return None

    def publish(self, ref: ListingRef) -> AdapterResult:
        p = self._set_status(ref.external_id, "ACTIVE")
        pub = self._online_store_publication()
        if pub:
            d = self.gql("""mutation($id: ID!, $input: [PublicationInput!]!){ publishablePublish(id: $id, input: $input){
                userErrors{ field message } } }""", {"id": ref.external_id, "input": [{"publicationId": pub}]})
            if d["publishablePublish"]["userErrors"]:
                raise IntegrationError(f"Shopify could not publish to the Online Store: {d['publishablePublish']['userErrors']}")
        url = p.get("onlineStoreUrl") or (f"https://{self.shop_domain}/products/{p['handle']}" if p.get("handle") else None)
        return AdapterResult(ref.external_id, url, "live", "Live on Shopify.")

    def withdraw(self, ref: ListingRef, reason: str) -> AdapterResult:
        self._set_status(ref.external_id, "ARCHIVED")
        return AdapterResult(ref.external_id, ref.external_url, "sold" if reason == "sold" else "withdrawn",
                             "Archived in Shopify.")

    def mark_reserved(self, ref: ListingRef) -> AdapterResult:
        self._set_status(ref.external_id, "DRAFT")
        return AdapterResult(ref.external_id, ref.external_url, "reserved", "Hidden from the Shopify store while reserved.")

    def mark_available(self, ref: ListingRef) -> AdapterResult:
        return self.publish(ref)

    def check_status(self, ref: ListingRef) -> AdapterResult:
        d = self.gql("query($id: ID!){ product(id: $id){ id status onlineStoreUrl } }", {"id": ref.external_id})
        p = d["product"]
        if p is None:
            return AdapterResult(ref.external_id, None, "withdrawn", "Product no longer exists in Shopify.")
        status = {"ACTIVE": "live", "DRAFT": "draft", "ARCHIVED": "withdrawn"}.get(p["status"], p["status"].lower())
        return AdapterResult(p["id"], p.get("onlineStoreUrl") or ref.external_url, status, f"Shopify status: {p['status']}")
