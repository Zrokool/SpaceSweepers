"""NASA PSI (Physical Sciences Informatics) REST client.

PSI's REST API is public, needs no key and returns JSON. It is the backend of
https://psi.nasa.gov/physci/repo/. It isn't officially documented, so every
response is checked before use and the app works from a committed snapshot.

Every URL is built here from fixed hosts and validated values; nothing a user
types is ever put into a URL. File downloads go through temporary (presigned)
links, which are only followed to PSI's own two S3 buckets.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx

PSI_ID = re.compile(r"^PSI-\d{1,5}$")
# PSI's own storage buckets. Test tables come from the first; documents (Reports, Science
# Documents) from the second. Only these exact hosts are followed, over HTTPS.
DOWNLOAD_HOSTS = ("psi-repo-prod.s3.amazonaws.com", "psi-curation-prod.s3.amazonaws.com")
SEARCH_PATH = "/geode-py/ws/repo/search"
RECORD_PATH = "/geode-py/ws/repo/investigations/{psi_id}"
DOWNLOAD_PATH = "/geode-py/ws/studies/{psi_id}/download"
# PSI's own pages, for links in the UI.
LANDING_URL = "https://psi.nasa.gov/physci/repo/data/investigations/{psi_id}"
COLLECTION_URL = "https://psi.nasa.gov/physci/repo/search?q=combustion&data_source=psi&data_type=investigation"


class PSIError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status   # the HTTP status, when PSI answered with an error

    @property
    def file_missing(self) -> bool:
        """PSI answered, but this one file isn't there (404/403/410): not a service outage."""
        return self.status in (403, 404, 410)


def check_id(psi_id: str) -> str:
    if not PSI_ID.match(psi_id):
        raise PSIError(f"not a PSI accession: {psi_id!r}")
    return psi_id


def check_download_url(url: str) -> str:
    """Only follow presigned links to PSI's own buckets, over HTTPS."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in DOWNLOAD_HOSTS or parts.port not in (None, 443):
        raise PSIError(f"unexpected download host: {parts.scheme}://{parts.hostname}")
    return url


class PSIClient:
    def __init__(self, http: httpx.AsyncClient, base: str = "https://psi.nasa.gov") -> None:
        self.http = http
        self.base = base.rstrip("/")

    async def _json(self, path: str, params: dict | None = None):
        resp = await self.http.get(self.base + path, params=params)
        if resp.status_code != 200:
            raise PSIError(f"PSI {path} returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise PSIError(f"PSI {path} returned something that isn't JSON") from None

    async def search(self, q: str = "combustion") -> list[dict]:
        """Search hits for `q`, as the PSI repository's search page issues them.

        The API returns every investigation for this query (133 on 2026-11-14);
        the search page then keeps the ones whose text matches the word. That
        filter is applied in sync.py so the snapshot holds the same set the
        page shows (26 for "combustion").
        """
        data = await self._json(SEARCH_PATH, {"q": q, "size": 200, "data_source": "psi",
                                              "data_type": "investigation"})
        try:
            hits = data["hits"]["hits"]
            return [h["_source"] for h in hits if PSI_ID.match(h["_source"].get("Accession", ""))]
        except (KeyError, TypeError):
            raise PSIError("PSI search response has an unexpected shape") from None

    async def record(self, psi_id: str) -> dict:
        data = await self._json(RECORD_PATH.format(psi_id=check_id(psi_id)))
        if not isinstance(data, dict) or data.get("accession") != psi_id:
            raise PSIError(f"PSI record for {psi_id} has an unexpected shape")
        return data

    async def download(self, psi_id: str, file_name: str, max_bytes: int) -> bytes:
        """Fetch one file through its presigned link, refusing anything over max_bytes."""
        resp = await self.http.get(self.base + DOWNLOAD_PATH.format(psi_id=check_id(psi_id)),
                                   params={"file": file_name, "redirect": "false"})
        if resp.status_code != 200:
            raise PSIError(f"PSI download link for {file_name} returned HTTP {resp.status_code}", resp.status_code)
        url = resp.text.strip().strip('"')
        if url.startswith("{"):
            try:
                url = resp.json().get("url", "")
            except ValueError:
                url = ""
        check_download_url(url)
        async with self.http.stream("GET", url) as file_resp:
            if file_resp.status_code != 200:
                raise PSIError(f"{file_name} returned HTTP {file_resp.status_code}", file_resp.status_code)
            size = int(file_resp.headers.get("content-length") or 0)
            if size > max_bytes:
                raise PSIError(f"{file_name} is {size} bytes, over the {max_bytes}-byte limit")
            chunks, total = [], 0
            async for chunk in file_resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise PSIError(f"{file_name} is over the {max_bytes}-byte limit")
                chunks.append(chunk)
        return b"".join(chunks)
