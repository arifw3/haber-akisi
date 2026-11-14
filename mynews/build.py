# coding=utf-8
"""Gunluk bulteni uretir: site/data/latest.json

PWA bu dosyayi okur. Ses dosyasi (MP3) varsa 'audio' alani doldurulur;
yoksa PWA tarayicinin kendi Turkce sesiyle (Web Speech API) okur.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .feeds import collect as collect_direct
from .gnews import NewsItem, check_feed
from .history import History, path_for
from .images import ImageResolver
from .rank import Ranker, Scored, load_config
from .speech import intro_for, normalize, summary_lead

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"

FAVICON = "https://www.google.com/s2/favicons?domain={domain}&sz=128"


def favicon_for(domain: str) -> str:
    return FAVICON.format(domain=domain) if domain else ""


def speech_text(publisher: str, title: str, summary: str = "", rules: str = "tr") -> str:
    """Hands-free modda seslendirilecek metin: kaynak, baslik, ozetin basi.

    Yalnizca yayincinin kendi yazdigini okur; LLM'e serbest metin
    yazdirilmaz, uydurma riski tasarimdan uzak tutulur.

    Eskiden burada iki sey daha vardi ve dinleyeni yoruyordu:
      - Google'in ilgili baslik listesinden secilen "ek cumle": cogu zaman
        baska bir yayincinin kose yazisi ya da yan haber basligiydi,
        anlatilan haberle ilgisi belirsizdi.
      - "Bu haberi 5 ayri kaynak yazdi" kuyrugu: haberlerin cogunda ayni
        cumle tekrar ediyordu; ustelik 5, Google'in kume buyuklugune
        koydugu ust sinir (bkz. rank.py). Bilgi zaten kartta rozet olarak var.
    """
    intro = intro_for(publisher, rules) or ("Google Haberler" if rules == "tr" else "Google News")
    # Iki nokta ust uste yerine nokta: TTS iki noktada duraklamiyordu.
    parts = [f"{intro}. {normalize(title, rules).rstrip('.')}."]
    lead = summary_lead(summary, title)
    if lead:
        parts.append(normalize(lead, rules).rstrip(".") + ".")
    return " ".join(parts)


def item_payload(scored: Scored, index: int, resolver: ImageResolver | None = None, unknown: str = "") -> dict:
    item = scored.item

    # Yayincinin kendi feed'inde eslesme varsa gorsel ve dogrudan baglanti
    # oradan gelir; yoksa alanlar bos kalir ve arayuz gradient gosterir.
    image, source_url, summary = "", "", ""

    # Dogrudan kaynak: gorsel, ozet ve baglanti zaten feed'den geldi.
    if item.direct:
        image = item.direct.get("image", "")
        summary = item.direct.get("summary", "")
        source_url = item.direct.get("source_url", "")
    elif resolver:
        match = resolver.resolve(item.title, item.domain)
        if match:
            image, source_url, summary = match.image, match.link, match.summary

    return {
        "id": f"{item.category}-{index}",
        "title": item.title,
        "publisher": item.publisher or unknown,
        "domain": item.domain,
        "favicon": favicon_for(item.domain),
        "published": item.published.isoformat(),
        "age_hours": round(item.age_hours, 1),
        "link": item.link,
        "image": image,
        "source_url": source_url,
        "summary": summary,
        "needs_translation": bool(item.direct.get("translate")),
        "source_count": item.source_count,
        "score": round(scored.score, 3),
        # Seslendirme metni burada degil, ceviriden sonra uretilir (bkz. build).
        "speech": "",
        "related": [
            {"title": r.title, "source": r.source}
            for r in item.related
            if r.title and r.title != item.title
        ][:4],
    }


def build(config: dict | None = None) -> dict:
    cfg = config or load_config()

    hist_cfg = cfg.get("history", {})
    history = (
        History(
            path_for(cfg.get("current_locale", "tr")),
            days=int(hist_cfg.get("days", 7)),
            threshold=float(hist_cfg.get("similarity", 0.6)),
        )
        if hist_cfg.get("enabled", True)
        else None
    )

    rules = cfg.get("speech_rules", "tr")
    unknown = "Bilinmeyen kaynak" if cfg.get("language", "tr") == "tr" else "Unknown source"
    locale_params = cfg.get("locale")

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

        # Dogrudan RSS/Atom kaynaklari (Google Haberler disi)
        if seg.get("sources"):
            direct_items, direct_health = collect_direct(
                seg["sources"], seg["key"], int(seg.get("max_age_days", 7))
            )
            pool.extend(direct_items)
            health.extend(direct_health)

        for topic in seg.get("topics", []):
            # Feed'ler arasinda kisa aralik: pes pese istek 503 tetikliyordu.
            if pool:
                time.sleep(1.2)
            report, items = check_feed(topic, seg["key"], locale_params)
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

        if history:
            before = len(pool)
            pool = [i for i in pool if not history.seen(i.title, i.link)]
            history.skipped += before - len(pool)

        chosen = Ranker(cfg, seg).select(pool, int(seg["limit"]))
        if history:
            for scored in chosen:
                history.remember(scored.item.title, scored.item.link)
        payloads = [item_payload(s, i, resolver, unknown) for i, s in enumerate(chosen)]

        # Ingilizce kaynaklar Turkce'ye cevrilir; ceviri basarisiz olursa
        # haberler Ingilizce kalir - bulteni kaybetmektense oyle yayinlanir.
        to_translate = [p for p in payloads if p.get("needs_translation")]
        for p in payloads:
            p.pop("needs_translation", None)
        if to_translate and cfg.get("translation", {}).get("enabled", True):
            try:
                from .translate import translate_items

                count = translate_items(to_translate, cfg.get("translation", {}))
                if count:
                    print(f"  {seg['title']}: {count} baslik Turkce'ye cevrildi")
            except Exception as exc:  # ceviri hicbir zaman bulteni dusurmemeli
                print(f"  {seg['title']}: ceviri atlandi ({str(exc)[:70]})")

        # Seslendirme metni ceviriden SONRA: once uretildiginde Ingilizce
        # kaynaklar Turkce bultende Turkce sesle Ingilizce okunuyordu.
        for scored, p in zip(chosen, payloads):
            p["speech"] = speech_text(scored.item.publisher, p["title"], p.get("summary", ""), rules)

        segments.append(
            {
                "key": seg["key"],
                "title": seg["title"],
                "items": payloads,
            }
        )

    if history:
        history.save()

    now = datetime.now(timezone.utc)
    return {
        "locale": cfg.get("current_locale", "tr"),
        "language": cfg.get("language", "tr"),
        "title": cfg.get("title", "Haber Akışı"),
        "date": now.date().isoformat(),
        "generated_at": now.isoformat(),
        "segments": segments,
        "health": health,
        "total": sum(len(s["items"]) for s in segments),
        "image_stats": resolver.stats if resolver else {},
        # Hic makale vermeyen yayinci beslemeleri denetime tasinsin.
        "empty_publisher_feeds": resolver.empty_feeds if resolver else [],
        "history_skipped": history.skipped if history else 0,
        "audio": None,
        "cues": [],
    }


def write(bulletin: dict, data_dir: Path = DATA_DIR) -> list[Path]:
    """Dile gore ayri klasore yazar: data/<dil>/latest.json"""
    locale = bulletin.get("locale", "tr")
    target = data_dir / locale
    target.mkdir(parents=True, exist_ok=True)
    paths = [target / "latest.json", target / f"{bulletin['date']}.json"]
    for path in paths:
        path.write_text(
            json.dumps(bulletin, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return paths
