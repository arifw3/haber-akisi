# coding=utf-8
"""Haber siralama: hangi 10 haber segmente girecek.

Ana sinyal: bir olayi kac farkli yayinci yazmis (Google News'in kendi
<ol><li> kumesinden geliyor). Canli veriyle dogrulandi: gercek gundem
maddeleri 4-5 kaynakta cikiyor, clickbait tek kaynakta kaliyor.

Skor = w_sources * log2(1+kaynak) + w_freshness * tazelik + w_trust * guven
        - clickbait_penalty * clickbait_orani
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .gnews import NewsItem

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.json"

# Turkce'ye ozgu kucultme: I -> i sorunu icin acik esleme
_TR_LOWER = str.maketrans("IİĞÜŞÖÇ", "iiğüşöç")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_STOPWORDS = {
    "ve", "ile", "bir", "bu", "da", "de", "için", "olarak", "sonra", "önce",
    "the", "a", "an", "of", "in", "on", "son", "dakika", "haberi", "haber",
    "oldu", "olan", "var", "yok", "daha", "çok", "ne", "mi", "mı", "ise",
}


LOCALE_DIR = CONFIG_PATH.parent / "locales"


def load_config(locale: str | None = None, path: Path | str | None = None) -> dict:
    """Ortak ayarlari dile ozel ayarlarla birlestirir.

    settings.json dilden bagimsiz olani tutar (skorlama, esikler, TTS);
    locales/<dil>.json ise segmentleri, yayincilari, kaliplari ve sesleri.
    """
    with open(path or CONFIG_PATH, encoding="utf-8") as fh:
        config = json.load(fh)

    locale = locale or config.get("default_locale", "tr")
    locale_path = LOCALE_DIR / f"{locale}.json"
    if not locale_path.exists():
        raise FileNotFoundError(f"Dil ayari bulunamadi: {locale_path}")

    with open(locale_path, encoding="utf-8") as fh:
        config.update(json.load(fh))

    config["current_locale"] = locale
    return config


def normalize(text: str) -> str:
    """Turkce duyarli kucultme + noktalama temizligi."""
    return _PUNCT_RE.sub(" ", text.translate(_TR_LOWER).lower()).strip()


def tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if len(t) > 2 and t not in _STOPWORDS}


def similarity(a: str, b: str) -> float:
    """Jaccard benzerligi - ayni olayin farkli basliklarini yakalar."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class Scored:
    item: NewsItem
    score: float
    sources: float
    freshness: float
    trust: float
    clickbait: float
    dropped: str = ""

    @property
    def kept(self) -> bool:
        return not self.dropped


class Ranker:
    def __init__(self, config: dict | None = None, segment: dict | None = None):
        """segment verilirse o segmentin scoring_override/min_trust ayarlari uygulanir.

        Bilim & Teknoloji feed'lerinde Google kumeleme yapmiyor (her haber tek
        kaynak gorunuyor), yani ana sinyalimiz orada calismiyor. O segmentte
        yayinci guveni ve clickbait cezasi daha baskin olmali.
        """
        self.cfg = config or load_config()
        segment = segment or {}
        self.s = dict(self.cfg["scoring"])
        self.s.update(segment.get("scoring_override", {}))
        self.min_trust = float(segment.get("min_trust", 0.0))
        self._drop = [normalize(p) for p in self.cfg.get("drop_patterns", [])]
        self._bait = [normalize(p) for p in self.cfg.get("clickbait_patterns", [])]

    # --- tekil sinyaller ---

    def trust_of(self, publisher: str) -> float:
        table = self.cfg.get("publisher_trust", {})
        if publisher in table:
            return float(table[publisher])
        norm = normalize(publisher)
        for name, value in table.items():
            if normalize(name) == norm:
                return float(value)
        return float(self.cfg.get("default_trust", 0.5))

    def freshness_of(self, age_hours: float) -> float:
        """1.0 (taze) -> 0.0 (max_age_hours'ta)."""
        cap = float(self.s.get("max_age_hours", 36))
        return max(0.0, 1.0 - max(age_hours, 0.0) / cap) if cap > 0 else 0.0

    def clickbait_of(self, title: str) -> float:
        """0..1 - kalip sayisi + noktalama/kapitalizasyon isaretleri."""
        norm = normalize(title)
        hits = sum(1 for p in self._bait if p and p in norm)
        if title.count("!") >= 1:
            hits += 1
        words = [w for w in title.split() if len(w) > 2]
        if words and sum(1 for w in words if w.isupper()) / len(words) > 0.4:
            hits += 1
        return min(hits / 3.0, 1.0)

    def drop_reason(self, item: NewsItem) -> str:
        norm = normalize(item.title)
        for pattern in self._drop:
            if pattern and pattern in norm:
                return f"format:{pattern}"
        if item.age_hours > float(self.s.get("max_age_hours", 36)):
            return "eski"
        if self.min_trust and self.trust_of(item.publisher) < self.min_trust:
            return f"dusuk_guven:{item.publisher}"
        return ""

    # --- skor ---

    def score(self, item: NewsItem) -> Scored:
        sources = math.log2(1 + item.source_count)
        freshness = self.freshness_of(item.age_hours)
        trust = self.trust_of(item.publisher)
        bait = self.clickbait_of(item.title)
        total = (
            float(self.s["w_sources"]) * sources
            + float(self.s["w_freshness"]) * freshness
            + float(self.s["w_trust"]) * trust
            - float(self.s["clickbait_penalty"]) * bait
        )
        return Scored(item, total, sources, freshness, trust, bait, self.drop_reason(item))

    # --- segment secimi ---

    def select(self, items: list[NewsItem], limit: int) -> list[Scored]:
        """Filtrele, sirala, benzer olaylari ve yayinci yigilmasini ele."""
        scored = sorted(
            (self.score(i) for i in items), key=lambda s: s.score, reverse=True
        )
        threshold = float(self.s.get("dedup_similarity", 0.55))
        cap = int(self.s.get("max_per_publisher", 3))

        chosen: list[Scored] = []
        per_publisher: dict[str, int] = {}
        for cand in scored:
            if not cand.kept:
                continue
            if per_publisher.get(cand.item.publisher, 0) >= cap:
                continue
            if any(similarity(cand.item.title, c.item.title) >= threshold for c in chosen):
                continue
            chosen.append(cand)
            per_publisher[cand.item.publisher] = per_publisher.get(cand.item.publisher, 0) + 1
            if len(chosen) >= limit:
                break
        return chosen
