# coding=utf-8
"""Yayinlanan bulteni denetler.

Sistem sessizce bozulabiliyor: Google bir feed'i degistirse, Gemini kotasi
dolsa, TTS anahtari sussa - her adim hatayi zarifce yutuyor ve is akisi
yesil kaliyor. Bu modul yayina cikan sonucu olcup esik altinda kalirsa
bagirmakla gorevli.

Onemli tasarim karari: denetim dagitimdan SONRA ve ayri calisir. Podcast
uretilemedi diye sitenin hic guncellenmemesi, eksik podcast'ten daha kotu
olurdu. Once yayinla, sonra uyar.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .gnews import fetch


@dataclass
class Report:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [c for c in self.checks if not c[1]]

    @property
    def ok(self) -> bool:
        return not self.failed

    def render(self) -> str:
        lines = []
        for name, ok, detail in self.checks:
            mark = "OK  " if ok else "HATA"
            lines.append(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
        lines.append("")
        lines.append("Tumu saglikli." if self.ok else f"{len(self.failed)} kontrol basarisiz.")
        return "\n".join(lines)


def age_hours(iso: str) -> float:
    try:
        stamp = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return float("inf")
    if not stamp.tzinfo:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600


def inspect(bulletin: dict, thresholds: dict | None = None) -> Report:
    """Bulteni esiklere gore denetle."""
    limits = {
        "min_items": 20,
        "max_age_hours": 36,
        "min_audio_ratio": 0.5,
        "min_podcast_turns": 4,
        "min_match_ratio": 0.15,
    }
    limits.update(thresholds or {})

    report = Report()
    items = [i for s in bulletin.get("segments", []) for i in s.get("items", [])]

    report.add(
        "haber sayisi",
        len(items) >= limits["min_items"],
        f"{len(items)} haber (en az {limits['min_items']})",
    )

    age = age_hours(bulletin.get("generated_at", ""))
    report.add(
        "bulten tazeligi",
        age <= limits["max_age_hours"],
        f"{age:.1f} saat once uretildi" if age != float("inf") else "tarih okunamadi",
    )

    # "quiet" bir arizadan cok bir gozlem: kaynak calisiyor ama yeni yazi
    # yok. Alarm listesine alinirsa denetim her gun kirmizi yanar ve
    # bakilmaz olur; ayri satirda bilgi olarak gosteriliyor.
    health = bulletin.get("health", [])
    problems = [h for h in health if h.get("status") not in ("ok", "quiet")]
    quiet = [h for h in health if h.get("status") == "quiet"]
    report.add(
        "kaynak feed'leri",
        not problems,
        ", ".join(f"{h['topic']}:{h['status']}" for h in problems) or "hepsi calisiyor",
    )
    if quiet:
        report.add(
            "sessiz kaynaklar",
            True,
            ", ".join(h["topic"] for h in quiet) + " (yeni yazi yok)",
        )

    if items:
        with_audio = [i for i in items if i.get("audio")]
        ratio = len(with_audio) / len(items)
        report.add(
            "seslendirme",
            ratio >= limits["min_audio_ratio"],
            f"{len(with_audio)}/{len(items)} haber sesli",
        )

    stats = bulletin.get("image_stats") or {}
    if stats.get("aranan"):
        ratio = stats.get("eslesen", 0) / stats["aranan"]
        report.add(
            "yayinci eslestirmesi",
            ratio >= limits["min_match_ratio"],
            f"%{ratio * 100:.0f} eslesme ({stats.get('eslesen')}/{stats['aranan']})",
        )

    turns = (bulletin.get("podcast") or {}).get("turns") or []
    report.add(
        "podcast bolumu",
        len(turns) >= limits["min_podcast_turns"],
        f"{len(turns)} replik",
    )

    return report


def fetch_bulletin(base_url: str, locale: str = "tr") -> dict:
    url = f"{base_url.rstrip('/')}/data/{locale}/latest.json"
    return json.loads(fetch(url, timeout=30).decode("utf-8"))
