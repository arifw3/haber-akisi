# coding=utf-8
"""Gunluk bulteni bir Google Doc'a yazar.

Neden Doc: NotebookLM, Google Docs kaynaklarini otomatik senkronluyor
(Mayis 2026'dan beri). Web linkleri ve PDF'ler senkronlanmiyor. Yani
bulteni her sabah ayni Doc'a yazarsak, notebook guncel icerigi
kendiliginden goruyor - elle yeniden eklemeye gerek kalmiyor.

Projedeki tek pip bagimliligi burasidir: servis hesabi JWT'si RS256 ile
imzalanmali, standart kutuphanede RSA imzalama yok. Bu modul yalnizca
--sync-doc kullanildiginda ice aktarilir; onun disinda proje bagimsiz
calismaya devam eder.

Ortam degiskenleri:
  GOOGLE_DOC_ID                  Hedef belgenin kimligi (URL'deki uzun dizge)
  GOOGLE_SERVICE_ACCOUNT_JSON    Servis hesabi anahtarinin JSON icerigi
"""
from __future__ import annotations

import json
import os

DOCS_API = "https://docs.googleapis.com/v1/documents"
SCOPES = ["https://www.googleapis.com/auth/documents"]


class DocSyncError(RuntimeError):
    pass


def _credentials(raw_json: str):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover - kurulum hatasi
        raise DocSyncError(
            "google-auth kurulu degil. 'pip install -r requirements.txt' calistirin."
        ) from exc

    try:
        info = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise DocSyncError("GOOGLE_SERVICE_ACCOUNT_JSON gecerli JSON degil") from exc

    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    creds.refresh(Request())
    return creds


def _call(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        if exc.code == 403:
            detail += (
                "\n  -> Belgeyi servis hesabinin e-postasiyla Duzenleyen (Editor) "
                "olarak paylastiginizdan emin olun."
            )
        raise DocSyncError(f"Docs API {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise DocSyncError(f"Docs API'ye ulasilamadi: {exc}") from exc


def _document_end_index(document: dict) -> int:
    """Belgedeki son karakterin indeksi.

    Docs API'de govde 1'den baslar ve sonda daima silinemeyen bir satir
    sonu vardir; bu yuzden silme araligi endIndex - 1'de biter.
    """
    content = document.get("body", {}).get("content", [])
    return max((element.get("endIndex", 1) for element in content), default=1)


def sync_document(text: str, document_id: str | None = None, credentials_json: str | None = None) -> int:
    """Belgenin icerigini bultenle degistir. Yazilan karakter sayisini dondurur."""
    document_id = document_id or os.environ.get("GOOGLE_DOC_ID")
    credentials_json = credentials_json or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not document_id:
        raise DocSyncError("GOOGLE_DOC_ID tanimli degil")
    if not credentials_json:
        raise DocSyncError("GOOGLE_SERVICE_ACCOUNT_JSON tanimli degil")

    creds = _credentials(credentials_json)
    document = _call("GET", f"{DOCS_API}/{document_id}", creds.token)
    end = _document_end_index(document)

    requests: list[dict] = []
    # Bos olmayan belgede once mevcut icerigi temizle.
    if end > 2:
        requests.append(
            {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end - 1}}}
        )
    requests.append({"insertText": {"location": {"index": 1}, "text": text}})

    _call(
        "POST",
        f"{DOCS_API}/{document_id}:batchUpdate",
        creds.token,
        {"requests": requests},
    )
    return len(text)


def service_account_email(credentials_json: str | None = None) -> str:
    """Belgeyi paylasmaniz gereken e-posta adresi."""
    raw = credentials_json or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    try:
        return json.loads(raw).get("client_email", "")
    except json.JSONDecodeError:
        return ""
