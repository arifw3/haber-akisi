# coding=utf-8
"""Google Haberler disindaki dogrudan RSS/Atom kaynaklari.

Laravel News, dev.to gibi teknik yayinlar Google Haberler'in Turkce
akislarinda cikmiyor. Bu modul onlari dogrudan cekip bultenin geri
kalaniyla ayni bicime donusturur.

Iki fark var:

- **Kaynak sinyali yok.** Google'in <ol><li> kumesi burada olmadigi icin
  "kac yayinci yazdi" olcusu calismaz; bu segmentlerde siralama tazelik
  ve kaynak guvenine dayanir (segment ayarlarindan).
- **Ozet dogrudan gelir.** Yayincinin kendi feed'i oldugu icin baslik,
  ozet, gorsel ve gercek baglanti tek istekte elde edilir - Google
  tarafinda ugrastigimiz eslestirmeye gerek kalmaz.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone

from .gnews import UA, FeedError, NewsItem, fetch
from .images import parse_articles


def _fetch_insecure(url: str, timeout: int = 25) -> bytes:
    """Sertifika dogrulamasi kapali cekim.

    Bazi kurumsal sunucular ara sertifikayi eksik gonderiyor (TUBITAK Bilim
    Genc boyle). Yalnizca herkese acik haber icerigi okundugu ve hicbir
    kimlik bilgisi gonderilmedigi icin bu kaynaklar icin kabul ediliyor;
    ayarda acikca "insecure" isaretlenmesi gerekir.
    """
    import ssl
    import urllib.request

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        return resp.read()


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def fetch_source(source: dict, category: str, max_age_days: int = 7) -> list[NewsItem]:
    """Tek bir dogrudan kaynagi cek ve NewsItem listesine cevir.

    Arsiv akislari yuzlerce eski yaziyi birden dondurebiliyor; bu yuzden
    tarih filtresi burada zorunlu. Tarihi olmayan ogeler atlanir.
    """
    url = source["url"]
    name = source.get("name") or urllib.parse.urlparse(url).netloc
    domain = urllib.parse.urlparse(source.get("site") or url).netloc
    if domain.startswith("www."):
        domain = domain[4:]

    try:
        raw = _fetch_insecure(url) if source.get("insecure") else fetch(url, timeout=25)
        articles = parse_articles(raw)
    except (FeedError, OSError):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    items: list[NewsItem] = []

    for article in articles:
        published = _parse_date(article.published)
        if not published or published < cutoff:
            continue

        item = NewsItem(
            id=article.link,
            title=article.title,
            publisher=name,
            publisher_url=f"https://{domain}" if domain else "",
            published=published,
            link=article.link,
            category=category,
            related=[],
        )
        # Yayinci feed'inden geldigi icin gorsel, ozet ve dogrudan baglanti
        # zaten elimizde; build asamasinda tekrar eslestirmeye gerek yok.
        item.direct = {
            "image": article.image,
            "summary": article.summary,
            "source_url": article.link,
            # Ceviri kaynak bazli: ayni segmentte Turkce ve Ingilizce
            # yayinlar birlikte bulunabiliyor.
            "translate": bool(source.get("translate")),
        }
        items.append(item)

    return items


def collect(sources: list[dict], category: str, max_age_days: int = 7) -> tuple[list[NewsItem], list[dict]]:
    """Segmentin tum dogrudan kaynaklarini topla; saglik raporunu da dondur."""
    items: list[NewsItem] = []
    health: list[dict] = []

    for source in sources:
        fetched = fetch_source(source, category, max_age_days)
        items.extend(fetched)
        health.append(
            {
                "topic": source.get("name") or source["url"],
                "segment": category,
                "status": "ok" if fetched else "empty",
                "count": len(fetched),
                "newest_age_hours": (
                    round(min(i.age_hours for i in fetched), 1) if fetched else None
                ),
                "error": "",
            }
        )

    return items, health
