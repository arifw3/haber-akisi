# coding=utf-8
"""Gunluk bulteni uretir: site/data/latest.json

PWA bu dosyayi okur. Ses dosyasi (MP3) varsa 'audio' alani doldurulur;
yoksa PWA tarayicinin kendi Turkce sesiyle (Web Speech API) okur.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .gnews import NewsItem, check_feed
from .images import ImageResolver
from .rank import Ranker, Scored, load_config, similarity

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"

FAVICON = "https://www.google.com/s2/favicons?domain={domain}&sz=128"


def favicon_for(domain: str) -> str:
    return FAVICON.format(domain=domain) if domain else ""


def speech_text(item: NewsItem, extra: str = "") -> str:
    """Hands-free modda seslendirilecek metin.

    Sadece basliklarda gecen bilgiyi kullanir - RSS govde vermiyor,
    uydurmamak icin bilincli olarak yuzeysel tutuluyor.
    """
    publisher = item.publisher or "Google Haberler"
    parts = [f"{publisher}: {item.title.rstrip('.')}."]
    if extra:
        parts.append(extra.rstrip(".") + ".")
    if item.source_count >= 3:
        parts.append(f"Bu haberi {item.source_count} ayrı kaynak yazdı.")
    return " ".join(parts)


def pick_extra(item: NewsItem) -> str:
    """Ilgili basliklardan en farkli olani ek cumle olarak kullan."""
    best, best_score = "", 1.0
    for rel in item.related:
        if not rel.title or rel.title == item.title:
            continue
        sim = similarity(item.title, rel.title)
        if sim < best_score:
            best, best_score = rel.title, sim
    # Cok benzerse ek bilgi tasimiyor demektir.
    if not best or best_score >= 0.6:
        return ""
    # Kose yazisi / bolunmus basliklar seslendirmeye uygun degil.
    lowered = best.casefold()
    if "|" in best or "köşe yazısı" in lowered or best.count(" - ") > 1:
        return ""
    return best


def item_payload(scored: Scored, index: int, resolver: ImageResolver | None = None) -> dict:
    item = scored.item

    # Yayincinin kendi feed'inde eslesme varsa gorsel ve dogrudan baglanti
    # oradan gelir; yoksa alanlar bos kalir ve arayuz gradient gosterir.
    image, source_url = "", ""
    if resolver:
        match = resolver.resolve(item.title, item.domain)
        if match:
            image, source_url = match.image, match.link

    return {
        "id": f"{item.category}-{index}",
        "title": item.title,
        "publisher": item.publisher or "Bilinmeyen kaynak",
        "domain": item.domain,
        "favicon": favicon_for(item.domain),
        "published": item.published.isoformat(),
        "age_hours": round(item.age_hours, 1),
        "link": item.link,
        "image": image,
        "source_url": source_url,
        "source_count": item.source_count,
        "score": round(scored.score, 3),
        "speech": speech_text(item, pick_extra(item)),
        "related": [
            {"title": r.title, "source": r.source}
            for r in item.related
            if r.title and r.title != item.title
        ][:4],
    }


def build(config: dict | None = None) -> dict:
    cfg = config or load_config()

    matching = cfg.get("image_matching", {})
    resolver = (
        ImageResolver(cfg.get("publisher_feeds", {}), float(matching.get("similarity", 0.5)))
        if matching.get("enabled")
        else None
    )

    segments: list[dict] = []
    health: list[dict] = []

    for seg in cfg["segments"]:
        pool: list[NewsItem] = []
        for topic in seg["topics"]:
            report, items = check_feed(topic, seg["key"])
            health.append(
                {
                    "topic": topic,
                    "segment": seg["key"],
                    "status": report.status,
                    "count": report.count,
                    "newest_age_hours": round(report.newest_age_hours, 1)
                    if report.newest_age_hours is not None
                    else None,
                    "error": report.error,
                }
            )
            pool.extend(items)

        chosen = Ranker(cfg, seg).select(pool, int(seg["limit"]))
        segments.append(
            {
                "key": seg["key"],
                "title": seg["title"],
                "items": [item_payload(s, i, resolver) for i, s in enumerate(chosen)],
            }
        )

    now = datetime.now(timezone.utc)
    return {
        "date": now.date().isoformat(),
        "generated_at": now.isoformat(),
        "segments": segments,
        "health": health,
        "total": sum(len(s["items"]) for s in segments),
        "image_stats": resolver.stats if resolver else {},
        "audio": None,
        "cues": [],
    }


def write(bulletin: dict, data_dir: Path = DATA_DIR) -> list[Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    paths = [data_dir / "latest.json", data_dir / f"{bulletin['date']}.json"]
    for path in paths:
        path.write_text(
            json.dumps(bulletin, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return paths
