"""Google Drive (photo inbox, finals) and Google Sheets (facts) through a service account.

Share only the listings folder and the one facts Sheet with the service account's email address.
These adapters use the official REST endpoints with google-auth (requirements-integrations.txt).
"""
from __future__ import annotations

import re
from typing import Any

from app.ingest.sources import IMAGE_EXT, IncomingFile
from app.integrations.base import Integration, IntegrationError, TestResult

DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets.readonly"]


class _GoogleBase(Integration):
    kind = "data"

    def _session(self):
        try:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account
        except ImportError as e:
            raise IntegrationError("Install requirements-integrations.txt to use Google Drive and Sheets.") from e
        path = self.settings.google_application_credentials
        if not path or not path.is_file():
            raise IntegrationError("GOOGLE_APPLICATION_CREDENTIALS does not point to a service-account JSON file.")
        creds = service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)
        return AuthorizedSession(creds)

    def _get(self, url: str, **params) -> dict:
        r = self._session().get(url, params=params, timeout=30)
        if r.status_code >= 400:
            raise IntegrationError(f"Google API error {r.status_code}: {r.text[:200]}", retryable=r.status_code >= 500)
        return r.json()


class GoogleDrive(_GoogleBase):
    name = "google_drive"
    label = "Google Drive"
    kind = "ingest"
    required_env = ("GOOGLE_APPLICATION_CREDENTIALS", "DRIVE_ROOT_FOLDER_ID")
    capabilities = ("read Inbox/", "copy originals", "write Finals/")
    notes = ("Folders expected under the root: Inbox/, Originals/, Finals/.",)

    def test(self) -> TestResult:
        d = self._get(f"{DRIVE}/files/{self.settings.drive_root_folder_id}", fields="id,name", supportsAllDrives="true")
        inbox = self.folder("Inbox")
        return TestResult(True, f"Drive folder '{d['name']}' reachable" + ("" if inbox else "; Inbox/ not found"),
                          {"inbox": bool(inbox)})

    def folder(self, name: str) -> str | None:
        q = (f"'{self.settings.drive_root_folder_id}' in parents and name = '{name}' and "
             "mimeType = 'application/vnd.google-apps.folder' and trashed = false")
        files = self._get(f"{DRIVE}/files", q=q, fields="files(id,name)", supportsAllDrives="true",
                          includeItemsFromAllDrives="true").get("files", [])
        return files[0]["id"] if files else None

    def list_inbox(self) -> list[dict[str, Any]]:
        inbox = self.folder("Inbox")
        if not inbox:
            return []
        out: list[dict[str, Any]] = []
        children = self._get(f"{DRIVE}/files", q=f"'{inbox}' in parents and trashed = false",
                             fields="files(id,name,mimeType,size)", supportsAllDrives="true",
                             includeItemsFromAllDrives="true", pageSize=500).get("files", [])
        for f in children:
            if f["mimeType"] == "application/vnd.google-apps.folder":
                sub = self._get(f"{DRIVE}/files", q=f"'{f['id']}' in parents and trashed = false",
                                fields="files(id,name,mimeType,size)", supportsAllDrives="true",
                                includeItemsFromAllDrives="true", pageSize=500).get("files", [])
                out += [{**s, "group": f["name"]} for s in sub]
            else:
                out.append({**f, "group": None})
        return [f for f in out if any(f["name"].lower().endswith(e) for e in IMAGE_EXT)]

    def download(self, file_id: str) -> bytes:
        r = self._session().get(f"{DRIVE}/files/{file_id}", params={"alt": "media", "supportsAllDrives": "true"}, timeout=120)
        if r.status_code >= 400:
            raise IntegrationError(f"Drive download failed ({r.status_code}).", retryable=r.status_code >= 500)
        return r.content


class DriveInbox:
    """IngestSource wrapper around Google Drive's Inbox/ folder."""

    name = "google_drive"

    def __init__(self) -> None:
        self.drive = GoogleDrive()

    def is_available(self) -> bool:
        return self.drive.is_configured()

    def list_pending(self) -> list[IncomingFile]:
        return [IncomingFile(ref=f["id"], name=f["name"], size=int(f.get("size") or 0), group=f.get("group"),
                             source=self.name) for f in self.drive.list_inbox()]

    def fetch(self, item: IncomingFile) -> bytes:
        return self.drive.download(item.ref)

    def mark_imported(self, item: IncomingFile) -> None:
        originals = self.drive.folder("Originals")
        if not originals:
            return
        s = self.drive._session()
        meta = s.get(f"{DRIVE}/files/{item.ref}", params={"fields": "parents", "supportsAllDrives": "true"}, timeout=30).json()
        s.patch(f"{DRIVE}/files/{item.ref}", params={"addParents": originals, "removeParents": ",".join(meta.get("parents", [])),
                                                    "supportsAllDrives": "true"}, timeout=30)


class GoogleSheets(_GoogleBase):
    name = "google_sheets"
    label = "Google Sheets (facts)"
    required_env = ("GOOGLE_APPLICATION_CREDENTIALS", "FACTS_SHEET_ID")
    capabilities = ("read one row per SKU", "suggest missing facts")
    notes = ("Values from the Sheet arrive as suggestions you confirm; they never overwrite the record silently.",)

    HEADER_MAP = {
        "sku": "sku", "brand": "brand", "model": "model", "reference": "reference", "ref": "reference",
        "year": "year", "condition": "condition_notes", "set": "box_papers_notes", "box & papers": "box_papers_notes",
        "custody": "custody", "price sgd": "price_sgd", "price (sgd)": "price_sgd", "price usd": "price_usd",
        "price (usd)": "price_usd", "consignor": "consignor_name", "notes": "description",
    }

    def test(self) -> TestResult:
        d = self._get(f"{SHEETS}/{self.settings.facts_sheet_id}", fields="properties.title")
        return TestResult(True, f"Sheet '{d['properties']['title']}' reachable.")

    def rows(self) -> list[dict[str, str]]:
        d = self._get(f"{SHEETS}/{self.settings.facts_sheet_id}/values/{self.settings.facts_sheet_range}")
        values = d.get("values", [])
        if not values:
            return []
        header = [self.HEADER_MAP.get(re.sub(r"\s+", " ", h.strip().lower()), None) for h in values[0]]
        out = []
        for row in values[1:]:
            rec = {header[i]: v.strip() for i, v in enumerate(row) if i < len(header) and header[i] and v.strip()}
            if rec.get("sku"):
                out.append(rec)
        return out

    def row_for(self, sku: str) -> dict[str, str] | None:
        for r in self.rows():
            if r["sku"].strip().upper() == sku.strip().upper():
                return r
        return None
