# coding=utf-8
"""Gunler arasi tekrar elemesi.

Gundemde birkac gun kalan bir haber her sabah yeniden sunuluyordu;
podcast'te de tekrar anlatiliyordu. Burasi son gunlerde gosterilen
haberleri hatirlar ve benzerlerini eler.

Neden ayri ve hafif bir dosya: Actions her calismada temiz checkout
yapiyor ve bulten artik depoya islenmiyor. Bu yuzden gecmis, tam
bultenler yerine kucuk bir imza dosyasinda tutuluyor ve is akisinda
actions/cache ile tasiniyor.

Elemede baslik benzerligi kullanilir; ayni olay farkli baslikla
gelse de yakalanir. Baslik belirgin degistiyse (yeni gelisme)
benzerlik dusecegi icin haber tekrar gecer - istenen davranis budur.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .rank import normalize, similarity

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "history.json"


class History:
    def __init__(self, path: Path | None = None, days: int = 7, threshold: float = 0.6):
        self.path = Path(path) if path else DEFAULT_PATH
        self.days = days
        self.threshold = threshold
        self.entries: list[dict] = self._load()
        self.skipped = 0

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        # Bugunun kayitlari haric tutulur: ayni gun ikinci kez uretim
        # yapildiginda bulten bosalmamali. Yalnizca onceki gunler "gorulmus"
        # sayilir.
        today = date.today().isoformat()
        cutoff = (date.today() - timedelta(days=self.days)).isoformat()
        return [
            e for e in data
            if isinstance(e, dict) and cutoff <= e.get("date", "") < today
        ]

    @property
    def titles(self) -> list[str]:
        return [e["title"] for e in self.entries if e.get("title")]

    def seen(self, title: str, url: str = "") -> bool:
        """Bu haber son gunlerde gosterildi mi?"""
        if url:
            for entry in self.entries:
                if entry.get("url") and entry["url"] == url:
                    return True

        for known in self.titles:
            if similarity(title, known) >= self.threshold:
                return True
        return False

    def remember(self, title: str, url: str = "") -> None:
        self.entries.append(
            {"title": title, "url": url, "date": date.today().isoformat()}
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # _load bugunku kayitlari disarida biraktigi icin dosyadakileri
        # kaybetmemek adina geri okuyup birlestiriyoruz.
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                stored = []
            known = {(e.get("title"), e.get("date")) for e in self.entries}
            cutoff = (date.today() - timedelta(days=self.days)).isoformat()
            for entry in stored:
                if not isinstance(entry, dict) or entry.get("date", "") < cutoff:
                    continue
                if (entry.get("title"), entry.get("date")) not in known:
                    self.entries.append(entry)
        # Ayni basligi iki kez tutmaya gerek yok.
        seen_keys: set[str] = set()
        unique: list[dict] = []
        for entry in reversed(self.entries):
            key = normalize(entry.get("title", ""))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique.append(entry)
        unique.reverse()

        self.path.write_text(
            json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8"
        )
