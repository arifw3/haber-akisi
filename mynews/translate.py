# coding=utf-8
"""Ingilizce basliklari ve ozetleri Turkce'ye cevirir.

Teknik yayinlar (Laravel News, dev.to) Ingilizce yayin yapiyor. Bu modul
Gemini ile ceviri yapar; orijinal metin de saklanir, boylece kaynaga
gidildiginde ne okunacagi bellidir.

Iki disiplin:

1. **Terimler korunur.** "queue", "middleware", "pull request" gibi
   ifadeler Turkcelestirilmeye calisilmaz; urun ve teknoloji adlari
   (Laravel, PHP, GitHub) oldugu gibi kalir.
2. **Onbellek.** Ceviri metnin hash'ine gore saklanir; ayni yazi ertesi
   gun akista kalirsa yeniden cevrilmez. Gunluk kota bosa harcanmaz.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .script import ScriptError, _post

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.6-flash"

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "translations.json"

RULES = """Aşağıdaki yazılım/teknoloji haberlerini Türkçe'ye çevir.

KURALLAR:
- Teknik terimleri çevirme: queue, middleware, pull request, deploy, cache,
  framework, release, commit, endpoint, migration gibi ifadeler İngilizce kalsın.
- Ürün, teknoloji ve şirket adlarını olduğu gibi bırak: Laravel, PHP, GitHub,
  Composer, Eloquent, Vue, React...
- Sürüm numaralarını ve kod parçalarını değiştirme.
- Doğal Türkçe kur; kelime kelime çeviri yapma.
- Başlıkları kısa tut, haber başlığı gibi olsun.
- Hiçbir bilgi ekleme veya çıkarma."""


class TranslationError(RuntimeError):
    pass


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def load_cache(path: Path = CACHE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(cache: dict, path: Path = CACHE_PATH, keep: int = 2000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(cache) > keep:
        cache = dict(list(cache.items())[-keep:])
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def translate_batch(texts: list[str], config: dict | None = None) -> list[str]:
    """Metin listesini tek istekte cevir. Sira korunur."""
    if not texts:
        return []

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise TranslationError("GEMINI_API_KEY tanimli degil")

    config = config or {}
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    prompt = (
        f"{RULES}\n\n"
        f"Çevrilecek metinler:\n{numbered}\n\n"
        "Çıktıyı JSON dizisi olarak ver: girdiyle aynı sırada, aynı sayıda öğe."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
    }

    try:
        data = _post(
            GEMINI_URL.format(model=config.get("model", DEFAULT_MODEL)),
            payload,
            {"x-goog-api-key": key, "Content-Type": "application/json"},
        )
        parsed = json.loads(data)
        result = json.loads(parsed["candidates"][0]["content"]["parts"][0]["text"])
    except ScriptError as exc:
        raise TranslationError(str(exc)) from exc
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise TranslationError(f"Ceviri ayristirilamadi: {exc}") from exc

    if len(result) != len(texts):
        raise TranslationError(f"Ceviri sayisi uyusmuyor: {len(result)} != {len(texts)}")
    return [str(r).strip() for r in result]


def translate_items(items: list, config: dict | None = None) -> int:
    """Haberlerin baslik ve ozetlerini yerinde cevir.

    Orijinaller title_en / summary_en olarak saklanir. Onbellekte olan
    metinler yeniden cevrilmez. Ceviri basarisiz olursa haberler
    Ingilizce kalir - bulteni kaybetmektense cevirisiz yayinlamak iyidir.
    """
    cache = load_cache()
    pending: list[str] = []

    for item in items:
        for text in (item.get("title"), item.get("summary")):
            if text and _key(text) not in cache and text not in pending:
                pending.append(text)

    if pending:
        batch_size = int((config or {}).get("batch_size", 25))
        for start in range(0, len(pending), batch_size):
            chunk = pending[start : start + batch_size]
            for original, translated in zip(chunk, translate_batch(chunk, config)):
                cache[_key(original)] = translated
        save_cache(cache)

    changed = 0
    for item in items:
        title = item.get("title")
        if title and _key(title) in cache:
            item["title_en"] = title
            item["title"] = cache[_key(title)]
            changed += 1
        summary = item.get("summary")
        if summary and _key(summary) in cache:
            item["summary_en"] = summary
            item["summary"] = cache[_key(summary)]

    return changed
