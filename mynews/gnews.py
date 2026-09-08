# coding=utf-8
"""Google News RSS'ten haber cekme ve ayristirma.

Sadece standart kutuphane kullanir; pip bagimliligi yoktur.

Google News RSS'in bize verdikleri (arastirmayla dogrulandi):
  - baslik + yayinci adi  ("Baslik - Hurriyet" biciminde)
  - <source url="..."> ile yayincinin alan adi
  - <description> icinde <ol><li> listesi: ayni olayin farkli yayincilardaki
    hallerini Google zaten grupluyor. Bu liste bizim "kac kaynak yazdi"
    onem sinyalimiz.

Vermedikleri:
  - makale govdesi (description sadece bu liste)
  - gorsel (media:content / enclosure / thumbnail hicbiri yok)
  - yayinciya dogrudan link (linkler CBMi... seklinde kodlu ve
    sunucu tarafinda cozulemiyor; yonlendirmeyi tarayicida JS yapiyor)
"""
from __future__ import annotations

import gzip
import html
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

TOPIC_BASE = "https://news.google.com/rss/headlines/section/topic/{topic}"
SEARCH_BASE = "https://news.google.com/rss/search"
LOCALE = {"hl": "tr", "gl": "TR", "ceid": "TR:tr"}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# <li><a href="...">BASLIK</a>  <font color="#6f6f6f">KAYNAK</font></li>
_LI_RE = re.compile(
    r"<li>\s*<a[^>]*href=\"(?P<link>[^\"]*)\"[^>]*>(?P<title>.*?)</a>"
    r".*?<font[^>]*>(?P<source>.*?)</font>\s*</li>",
    re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class FeedError(RuntimeError):
    """Feed cekilemedi veya ayristirilamadi."""


@dataclass
class Related:
    """Ayni olayin baska bir yayincidaki hali."""

    title: str
    source: str
    link: str = ""


@dataclass
class NewsItem:
    id: str
    title: str
    publisher: str
    publisher_url: str
    published: datetime
    link: str
    category: str
    related: list[Related] = field(default_factory=list)

    @property
    def domain(self) -> str:
        host = urllib.parse.urlparse(self.publisher_url).netloc
        return host[4:] if host.startswith("www.") else host

    @property
    def source_count(self) -> int:
        """Bu olayi kac farkli yayinci yazmis (kendisi dahil)."""
        names = {self.publisher.casefold()} if self.publisher else set()
        names.update(r.source.casefold() for r in self.related if r.source)
        return max(len(names), 1)

    @property
    def age_hours(self) -> float:
        return (_now() - self.published).total_seconds() / 3600.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(raw: str) -> str:
    """HTML etiketlerini at, bosluklari tekille, entity'leri coz."""
    return _WS_RE.sub(" ", _TAG_RE.sub("", html.unescape(raw or ""))).strip()


def _topic_url(topic: str) -> str:
    return TOPIC_BASE.format(topic=topic) + "?" + urllib.parse.urlencode(LOCALE)


def search_url(query: str) -> str:
    params = dict(LOCALE)
    params["q"] = query
    return SEARCH_BASE + "?" + urllib.parse.urlencode(params)


def fetch(url: str, timeout: int = 25) -> bytes:
    """URL'yi cek. Google gzip donebilir, acmayi biz halledelim."""
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw
    except urllib.error.URLError as exc:
        raise FeedError(f"{url} cekilemedi: {exc}") from exc


def split_title(raw: str) -> tuple[str, str]:
    """'Baslik - Yayinci' -> ('Baslik', 'Yayinci').

    Baslikta da tire olabilir; yayinci adi hep en sondaki ' - ' sonrasi.
    Ayirici yoksa yayinci bos doner.
    """
    text = _clean(raw)
    idx = text.rfind(" - ")
    if idx == -1:
        return text, ""
    title, publisher = text[:idx].strip(), text[idx + 3 :].strip()
    # Cok uzun bir "yayinci" muhtemelen basligin parcasi.
    if not publisher or len(publisher) > 40:
        return text, ""
    return title, publisher


def parse_related(description: str) -> list[Related]:
    """<description> icindeki <ol><li> listesini cikar."""
    out: list[Related] = []
    for m in _LI_RE.finditer(html.unescape(description or "")):
        title = _clean(m.group("title"))
        source = _clean(m.group("source"))
        if title:
            out.append(Related(title=title, source=source, link=m.group("link")))
    return out


def parse_feed(raw: bytes, category: str) -> list[NewsItem]:
    """RSS XML -> NewsItem listesi."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FeedError(f"{category}: XML ayristirilamadi: {exc}") from exc

    items: list[NewsItem] = []
    for node in root.findall(".//item"):
        raw_title = node.findtext("title") or ""
        title, publisher_from_title = split_title(raw_title)
        if not title:
            continue

        src = node.find("source")
        publisher = (src.text or "").strip() if src is not None and src.text else ""
        publisher = publisher or publisher_from_title
        publisher_url = (src.get("url") or "") if src is not None else ""

        published = _parse_date(node.findtext("pubDate"))
        guid = (node.findtext("guid") or node.findtext("link") or title).strip()

        items.append(
            NewsItem(
                id=guid,
                title=title,
                publisher=publisher,
                publisher_url=publisher_url,
                published=published,
                link=(node.findtext("link") or "").strip(),
                category=category,
                related=parse_related(node.findtext("description") or ""),
            )
        )
    return items


def _parse_date(value: str | None) -> datetime:
    if not value:
        return _now()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return _now()
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fetch_topic(topic: str, category: str) -> list[NewsItem]:
    """Bir Google News konu feed'ini cek ve ayristir."""
    return parse_feed(fetch(_topic_url(topic)), category)


@dataclass
class FeedHealth:
    topic: str
    ok: bool
    count: int = 0
    newest_age_hours: float | None = None
    error: str = ""

    @property
    def status(self) -> str:
        if not self.ok:
            return "broken"
        if self.count == 0:
            return "empty"
        if self.newest_age_hours is not None and self.newest_age_hours > 48:
            return "stale"
        return "ok"


def check_feed(topic: str, category: str) -> tuple[FeedHealth, list[NewsItem]]:
    """Feed'i cek ve sagligini raporla. Bozuk feed sessizce bos donmemeli."""
    try:
        items = fetch_topic(topic, category)
    except FeedError as exc:
        return FeedHealth(topic=topic, ok=False, error=str(exc)), []
    newest = min((i.age_hours for i in items), default=None)
    return FeedHealth(topic=topic, ok=True, count=len(items), newest_age_hours=newest), items
