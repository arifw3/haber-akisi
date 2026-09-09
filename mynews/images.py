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
from dataclasses import dataclass

from .gnews import FeedError, fetch
from .rank import similarity

MRSS = "{http://search.yahoo.com/mrss/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
_IMG_RE = re.compile(r"""<img[^>]+src=["']([^"']+)""", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SUMMARY_MAX = 1800


@dataclass
class Article:
    title: str
    link: str
    image: str
    summary: str = ""


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
        link = (item.findtext("link") or "").strip()
        if title and link.startswith("http"):
            articles.append(
                Article(title, link, extract_image(item), extract_summary(item))
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

    def _articles_for(self, domain: str) -> list[Article]:
        if domain in self._cache:
            return self._cache[domain]

        articles: list[Article] = []
        for url in self.feeds.get(domain, []):
            try:
                articles.extend(parse_articles(fetch(url, timeout=20)))
            except (FeedError, OSError):
                continue
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
