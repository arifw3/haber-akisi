# coding=utf-8
"""Yayinci RSS'lerinden gorsel ve dogrudan makale baglantisi eslestirir.

Google Haberler RSS ne gorsel ne de yayinciya dogrudan link veriyor
(linkler CBMi... seklinde kodlu ve sunucu tarafinda cozulemiyor). Ama
yayincinin adi ve alan adi elimizde. Yayincinin kendi RSS'ini cekip
basliklari eslestirince ikisi birden geliyor.

Kapsam kismidir ve oyle olmasi normaldir: her yayincinin feed'i yok,
bazi feed'ler gorsel tasimiyor, haber feed'den dusmus olabilir.
Eslesme bulunamayan haber kategorisine gore gradient ile gosterilir.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from dataclasses import dataclass

from email.utils import parsedate_to_datetime

from .gnews import FeedError, fetch
from .rank import similarity

ATOM = "{http://www.w3.org/2005/Atom}"
MRSS = "{http://search.yahoo.com/mrss/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
_IMG_RE = re.compile(r"""<img[^>]+src=["']([^"']+)""", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SUMMARY_MAX = 1800


def extract_date(item: ET.Element, atom: bool = False) -> str:
    """Yayin zamanini ISO olarak dondur. Bulunamazsa bos."""
    fields = (f"{ATOM}published", f"{ATOM}updated") if atom else ("pubDate", "date")
    for field in fields:
        raw = (item.findtext(field) or "").strip()
        if not raw:
            continue
        try:
            return parsedate_to_datetime(raw).isoformat()
        except (TypeError, ValueError):
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
        except ValueError:
            continue
    return ""


@dataclass
class Article:
    title: str
    link: str
    image: str
    summary: str = ""
    published: str = ""   # ISO 8601; bos ise tarih bulunamamistir


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html.unescape(text or ""))).strip()


def extract_image(item: ET.Element) -> str:
    """Feed'lerin gorseli tasidigi dort ayri yeri sirayla dener."""
    for tag in (MRSS + "content", MRSS + "thumbnail"):
        node = item.find(tag)
        if node is not None and node.get("url"):
            return node.get("url")

    enclosure = item.find("enclosure")
    if enclosure is not None and enclosure.get("url"):
        kind = enclosure.get("type") or ""
        if not kind or kind.startswith("image"):
            return enclosure.get("url")

    for field in ("description", CONTENT):
        match = _IMG_RE.search(html.unescape(item.findtext(field) or ""))
        if match:
            return match.group(1)

    node = item.find("image")
    if node is not None and (node.text or "").startswith("http"):
        return node.text.strip()

    return ""


def extract_summary(item: ET.Element) -> str:
    """Feed'deki ozet metni. content:encoded genelde description'dan uzun.

    Bu metin haberin gercek govdesinden geliyor; senaryo yazarken LLM'in
    uydurmadan baglam kurabilmesini saglayan sey bu.
    """
    candidates = [_clean(item.findtext(field) or "") for field in ("description", CONTENT)]
    best = max(candidates, key=len) if candidates else ""
    return best[:_SUMMARY_MAX]


def _item_link(item: ET.Element) -> str:
    """RSS ogesinin baglantisi.

    Duz <link> beklenir ama herkes oyle yazmiyor: Milliyet RSS ogesinin
    icinde <atom:link href="..."> kullaniyor. Duz <link> arayan parser
    bu feed'in 20 ogesinin tamamini sessizce atiyordu — feed saglikli,
    haberler oradaydi, biz goremiyorduk.
    """
    link = (item.findtext("link") or "").strip()
    if link.startswith("http"):
        return link

    for node in item.findall(f"{ATOM}link"):
        rel = node.get("rel") or "alternate"
        href = (node.get("href") or "").strip()
        if rel == "alternate" and href.startswith("http"):
            return href
    return ""


def parse_articles(raw: bytes) -> list[Article]:
    """Bozuk XML yaygin: once dogrudan, sonra temizlenmis halini dene."""
    root = None
    for attempt in (raw, _sanitize(raw)):
        try:
            root = ET.fromstring(attempt)
            break
        except ET.ParseError:
            continue
    if root is None:
        return []

    articles = []
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title"))
        link = _item_link(item)
        if title and link.startswith("http"):
            articles.append(
                Article(title, link, extract_image(item), extract_summary(item), extract_date(item))
            )

    # Atom akislari <entry> kullanir; bircok gelistirici blogu bu bicimde.
    for entry in root.findall(f".//{ATOM}entry"):
        title = _clean(entry.findtext(f"{ATOM}title"))
        link = ""
        for node in entry.findall(f"{ATOM}link"):
            rel = node.get("rel") or "alternate"
            if rel == "alternate" and node.get("href"):
                link = node.get("href").strip()
                break
        if not (title and link.startswith("http")):
            continue

        summary = ""
        for field in (f"{ATOM}summary", f"{ATOM}content"):
            candidate = _clean(entry.findtext(field) or "")
            if len(candidate) > len(summary):
                summary = candidate
        articles.append(
            Article(title, link, extract_image(entry), summary[:_SUMMARY_MAX], extract_date(entry, atom=True))
        )

    return articles


def _sanitize(raw: bytes) -> bytes:
    """BOM, kacak & ve XML'de yasak kontrol karakterlerini temizle."""
    text = raw.decode("utf-8", "ignore").lstrip("﻿\r\n\t ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    # Varlik olmayan ciplak & isaretleri ayristiriciyi bozuyor.
    text = re.sub(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#x[0-9a-fA-F]+);)", "&amp;", text)
    return text.encode("utf-8")


class ImageResolver:
    """Alan adina gore yayinci feed'lerini cekip basliklari eslestirir."""

    def __init__(self, feeds: dict[str, list[str]], threshold: float = 0.5):
        self.feeds = feeds
        self.threshold = threshold
        self._cache: dict[str, list[Article]] = {}
        self.stats = {"aranan": 0, "eslesen": 0, "gorselli": 0, "ozetli": 0}
        # Hic makale vermeyen yayinci beslemeleri. Bunlar sessizce
        # bosaliyordu: URL olmus ya da bicim degismis, kod hatayi yutuyor,
        # haber gorselsiz kaliyor ve kimse sebebini bilmiyor. 2026-09-11'de
        # 14 beslemenin 5'i bu durumdaydi.
        self.empty_feeds: list[str] = []

    def _articles_for(self, domain: str) -> list[Article]:
        if domain in self._cache:
            return self._cache[domain]

        articles: list[Article] = []
        for url in self.feeds.get(domain, []):
            try:
                articles.extend(parse_articles(fetch(url, timeout=20)))
            except (FeedError, OSError):
                continue

        if not articles and domain not in self.empty_feeds:
            self.empty_feeds.append(domain)

        self._cache[domain] = articles
        return articles

    def resolve(self, title: str, domain: str) -> Article | None:
        """Basligi yayincinin feed'indeki habere bagla."""
        if domain not in self.feeds:
            return None

        self.stats["aranan"] += 1
        best, best_score = None, 0.0
        for article in self._articles_for(domain):
            score = similarity(title, article.title)
            if score > best_score:
                best, best_score = article, score

        if not best or best_score < self.threshold:
            return None

        self.stats["eslesen"] += 1
        if best.image:
            self.stats["gorselli"] += 1
        if best.summary:
            self.stats["ozetli"] += 1
        return best
