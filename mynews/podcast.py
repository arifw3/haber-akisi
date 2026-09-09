# coding=utf-8
"""Podcast bolumu ve RSS akisi.

Replikler ayri dosyalar halinde uretiliyor (arayuz onlari sirayla caliyor).
Podcast uygulamalari ise tek bir dosya bekler; burasi replikleri birlestirip
bolumu olusturur ve iTunes uyumlu bir RSS yazar.

Birlestirme icin ffmpeg gerekmiyor: ayni kodek ve ornekleme hiziyla
uretilmis MP3 cerceveleri arka arkaya eklendiginde gecerli bir dosya olusur.
Sure, MP3 basligindan okunan bit hiziyla hesaplanir.
"""
from __future__ import annotations

import json
import struct
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"
EPISODE_DIR = SITE_DIR / "audio" / "episodes"
EPISODES_JSON = SITE_DIR / "data" / "episodes.json"

# MPEG-1 Layer III bit hizi tablosu (kbps)
_BITRATES = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_SAMPLE_RATES = {0: 44100, 1: 48000, 2: 32000}


def _first_frame_bitrate(data: bytes) -> int:
    """Ilk gecerli MPEG cercevesinden bit hizini (kbps) oku."""
    for i in range(min(len(data) - 4, 200000)):
        if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
            continue
        bitrate_index = (data[i + 2] & 0xF0) >> 4
        sample_index = (data[i + 2] & 0x0C) >> 2
        if bitrate_index in (0, 15) or sample_index == 3:
            continue
        return _BITRATES[bitrate_index]
    return 0


def duration_seconds(path: Path) -> int:
    """Kaba ama yeterli sure tahmini (sabit bit hizi varsayimiyla)."""
    data = path.read_bytes()
    bitrate = _first_frame_bitrate(data)
    if not bitrate:
        return 0
    return int(len(data) * 8 / (bitrate * 1000))


def merge_turns(turns: list[dict], site_dir: Path, out_path: Path) -> Path:
    """Replik seslerini tek bolum dosyasinda birlestir."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as target:
        for turn in turns:
            audio = site_dir / turn["audio"]
            if audio.exists():
                target.write(audio.read_bytes())
    return out_path


def format_duration(seconds: int) -> str:
    hours, rest = divmod(max(seconds, 0), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def load_episodes(path: Path = EPISODES_JSON) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_episodes(episodes: list[dict], path: Path = EPISODES_JSON) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8")


def build_episode(bulletin: dict, site_dir: Path = SITE_DIR, keep: int = 30) -> dict | None:
    """Gunun bolumunu uret, arsive ekle, eskileri temizle."""
    podcast = bulletin.get("podcast") or {}
    turns = podcast.get("turns") or []
    if not turns:
        return None

    date = bulletin["date"]
    path = merge_turns(turns, site_dir, site_dir / "audio" / "episodes" / f"{date}.mp3")

    headlines = [
        item["title"]
        for segment in bulletin.get("segments", [])
        for item in segment["items"][:2]
    ][:6]

    episode = {
        "date": date,
        "title": f"Haber Akışı — {date}",
        "audio": f"audio/episodes/{date}.mp3",
        "bytes": path.stat().st_size,
        "duration": duration_seconds(path),
        "turns": len(turns),
        "summary": "Bugünün öne çıkan haberleri: " + "; ".join(headlines),
        "published": datetime.now(timezone.utc).isoformat(),
    }

    episodes = [e for e in load_episodes(site_dir / "data" / "episodes.json") if e.get("date") != date]
    episodes.insert(0, episode)
    episodes = episodes[:keep]
    save_episodes(episodes, site_dir / "data" / "episodes.json")

    # Arsivden dusen bolumlerin ses dosyalarini sil.
    kept = {e["date"] for e in episodes}
    episode_dir = site_dir / "audio" / "episodes"
    for old in episode_dir.glob("*.mp3"):
        if old.stem not in kept:
            old.unlink(missing_ok=True)

    return episode


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_feed(episodes: list[dict], base_url: str, config: dict | None = None) -> str:
    """iTunes uyumlu podcast RSS."""
    config = config or {}
    title = config.get("title", "Haber Akışı")
    author = config.get("author", "Haber Akışı")
    description = config.get(
        "description",
        "Google Haberler'den derlenen günlük Türkçe haber bülteni. "
        "İki sunucu, günün öne çıkan haberleri, her sabah yeni bölüm.",
    )
    base = base_url.rstrip("/")
    image = f"{base}/icons/icon-512.png"

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"'
        ' xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        "<channel>",
        f"<title>{_esc(title)}</title>",
        f"<link>{_esc(base)}/</link>",
        f"<description>{_esc(description)}</description>",
        "<language>tr</language>",
        f"<itunes:author>{_esc(author)}</itunes:author>",
        f"<itunes:summary>{_esc(description)}</itunes:summary>",
        '<itunes:category text="News"/>',
        "<itunes:explicit>false</itunes:explicit>",
        f'<itunes:image href="{_esc(image)}"/>',
        f"<atom:link xmlns:atom='http://www.w3.org/2005/Atom' href='{_esc(base)}/podcast.xml'"
        " rel='self' type='application/rss+xml'/>",
    ]

    for episode in episodes:
        try:
            published = format_datetime(datetime.fromisoformat(episode["published"]))
        except (KeyError, ValueError):
            published = format_datetime(datetime.now(timezone.utc))

        url = f"{base}/{episode['audio']}"
        lines += [
            "<item>",
            f"<title>{_esc(episode['title'])}</title>",
            f"<description>{_esc(episode.get('summary', ''))}</description>",
            f"<pubDate>{published}</pubDate>",
            f"<guid isPermaLink=\"false\">{_esc(episode['date'])}</guid>",
            f'<enclosure url="{_esc(url)}" length="{episode.get("bytes", 0)}" type="audio/mpeg"/>',
            f"<itunes:duration>{format_duration(episode.get('duration', 0))}</itunes:duration>",
            f"<itunes:episodeType>full</itunes:episodeType>",
            "</item>",
        ]

    lines += ["</channel>", "</rss>"]
    return "\n".join(lines)


def write_feed(episodes: list[dict], site_dir: Path = SITE_DIR, base_url: str = "", config: dict | None = None) -> Path:
    path = site_dir / "podcast.xml"
    path.write_text(render_feed(episodes, base_url, config), encoding="utf-8")
    return path
