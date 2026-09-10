# coding=utf-8
"""Bultenden iki sunuculu Turkce podcast senaryosu uretir.

NotebookLM'in Audio Overview'una benzer bir format: iki sunucu haberleri
sirayla ele alir, aralarinda gecis yapar. Fark, kaynak disiplininde.

Uydurmayi engelleyen uc onlem:

1. Modele yalnizca elimizdeki metin veriliyor: baslik, yayincinin kendi
   ozeti ve ayni olayi yazan diger kaynaklarin basliklari. Baska hicbir
   sey yok.
2. Prompt, verilmeyen hicbir bilgiyi (sayi, tarih, isim, sebep-sonuc)
   eklememeyi acikca yasakliyor.
3. Uretim sonrasi dogrulayici, metinde gecen sayilarin kaynak metinde
   olup olmadigini kontrol ediyor; uyduruk sayi iceren replikler
   ayiklaniyor (bkz. verify_turns).

Ozeti olmayan haberler senaryoya girmiyor - baslikla yorum yapilmaz.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.6-flash"

RULES_TR = """Sen bir Türkçe haber podcast'i için senaryo yazıyorsun.
İki sunucu var: {a} ve {b}. Doğal, akıcı, sohbet havasında konuşuyorlar.

MUTLAK KURALLAR:
1. SADECE sana verilen haber metinlerindeki bilgiyi kullan. Hiçbir sayı,
   tarih, isim, yer veya sebep-sonuç ilişkisi EKLEME.
2. Kendi yorumunu, tahminini veya genel kültür bilgini KATMA.
3. Bir haberde detay azsa kısa geç; doldurma yapma.
4. Her haberde kaynağı an ("Hürriyet'in aktardığına göre" gibi).
5. Emin olmadığın hiçbir şeyi söyleme.

ÜSLUP:
- Kısa cümleler. Her replik en fazla 2-3 cümle.
- Sunucular birbirine soru sorabilir, ama cevap yalnızca verilen metinden gelir.
- Abartı, clickbait, duygusal yorum yok. Sakin ve bilgilendirici.
- Bölüm kısa bir selamlamayla başlar, kısa bir kapanışla biter.
- TÜM REPLİKLER TÜRKÇE OLMALI."""

RULES_EN = """You are writing the script for an English-language news podcast.
Two hosts: {a} and {b}. They speak naturally, like a real conversation.

ABSOLUTE RULES:
1. Use ONLY the information in the story texts given to you. Do NOT add any
   number, date, name, place or causal claim that is not there.
2. Do NOT add your own commentary, speculation or background knowledge.
3. If a story has little detail, keep it short. Never pad.
4. Attribute every story to its source ("according to BBC" and so on).
5. Never say anything you are not certain of.

STYLE:
- Short sentences. At most 2-3 sentences per turn.
- Hosts may ask each other questions, but answers come only from the given text.
- No hype, no clickbait, no emotional commentary. Calm and informative.
- Open with a brief greeting, close with a brief sign-off.
- ALL TURNS MUST BE IN ENGLISH."""

RULE_SETS = {"tr": RULES_TR, "en": RULES_EN}


class ScriptError(RuntimeError):
    pass


@dataclass
class Turn:
    speaker: str
    text: str


# Gecici hatalar: model asiri yuklu (503), hiz siniri (429), sunucu hatasi.
_RETRYABLE = {429, 500, 502, 503, 504}


# Gemini 429'da hangi limitin dolduguna ve ne kadar beklenmesi
# gerektigine dair ayrinti donuyor; ikisi de govdenin derinlerinde.
def _quota_detail(body: str) -> tuple[str, float]:
    """(limit adi, onerilen bekleme sn) — okunamazsa ("", 0)."""
    try:
        details = json.loads(body)["error"].get("details", [])
    except (json.JSONDecodeError, KeyError, TypeError):
        return "", 0.0

    limit, delay = "", 0.0
    for detail in details:
        kind = detail.get("@type", "")
        if kind.endswith("QuotaFailure"):
            violations = detail.get("violations") or [{}]
            limit = violations[0].get("quotaId") or violations[0].get("quotaMetric", "")
        elif kind.endswith("RetryInfo"):
            raw = str(detail.get("retryDelay", "")).rstrip("s")
            try:
                delay = float(raw)
            except ValueError:
                delay = 0.0
    return limit, delay


def _post(url: str, payload: dict, headers: dict, timeout: int = 120, attempts: int = 5) -> bytes:
    """Gecici hatalarda artan bekleme ile yeniden dener.

    Gemini hem 503 donuyor hem de dakikalik limitte 429. Beklemeler
    baslangicta cok kisaydi (toplam 21 sn): ceviri adimi tesadufen
    kurtuluyor, hemen ardindan gelen podcast adimi ayni limite carpip
    vazgeciyordu. Gunde bir kez calisan bir is icin birkac dakika
    beklemek, bolumun hic uretilmemesinden iyidir.

    Sunucu kendi bekleme suresini (RetryInfo) soyluyorsa ona uyulur.
    """
    body = json.dumps(payload).encode("utf-8")
    last = ""

    for attempt in range(attempts):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        suggested = 0.0
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            limit, suggested = _quota_detail(raw)
            # Hangi kotanin doldugu teshis icin sart; mesajin ilk 200
            # karakteri bu bilgiyi hic icermiyor.
            last = f"HTTP {exc.code}" + (f" [{limit}]" if limit else f": {raw[:120]}")
            if exc.code not in _RETRYABLE or attempt == attempts - 1:
                raise ScriptError(f"Gemini API {last}") from exc
        except urllib.error.URLError as exc:
            last = str(exc)
            if attempt == attempts - 1:
                raise ScriptError(f"Gemini API'ye ulasilamadi: {exc}") from exc

        wait = suggested if suggested else min(15 * 2 ** attempt, 90)
        wait = min(wait, 90) + random.uniform(0, 2)
        print(f"  Gemini gecici hata ({last[:80]}), {wait:.0f} sn sonra yeniden deneniyor…")
        time.sleep(wait)

    raise ScriptError(f"Gemini API: {last}")


def build_context(bulletin: dict, max_items: int = 12) -> tuple[str, list[str]]:
    """Modele verilecek kaynak metni ve dogrulama icin ham metin listesi.

    Yalnizca ozeti olan haberler alinir: baslikla yorum yapilmaz.
    """
    lines: list[str] = []
    raw: list[str] = []
    count = 0

    for segment in bulletin.get("segments", []):
        segment_items = [i for i in segment.get("items", []) if i.get("summary")]
        if not segment_items:
            continue

        lines.append(f"\n## BÖLÜM: {segment['title']}")
        for item in segment_items:
            if count >= max_items:
                break
            count += 1
            lines.append(f"\nHABER {count}")
            lines.append(f"Başlık: {item['title']}")
            lines.append(f"Kaynak: {item['publisher']}")
            lines.append(f"Özet: {item['summary']}")
            others = [f"{r['source']}: {r['title']}" for r in item.get("related", [])[:3]]
            if others:
                lines.append("Diğer kaynaklar: " + " | ".join(others))

            raw.append(" ".join([item["title"], item["summary"], " ".join(others)]))

    return "\n".join(lines), raw


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def verify_turns(turns: list[Turn], raw_sources: list[str]) -> tuple[list[Turn], list[str]]:
    """Kaynak metinde gecmeyen sayi iceren replikleri ayikla.

    Uydurma en cok sayilarda goruluyor ("3 kisi", "yuzde 40"). Model
    bir sayiyi kendi eklediyse o replik guvenilmez sayilir.
    """
    haystack = " ".join(raw_sources)
    source_numbers = set(_NUMBER_RE.findall(haystack))

    kept: list[Turn] = []
    dropped: list[str] = []
    for turn in turns:
        invented = [n for n in _NUMBER_RE.findall(turn.text) if n not in source_numbers]
        # Tek haneli sayilar siralama/gunluk dil olabilir ("iki haber", "3."),
        # asil risk kaynakta hic gecmeyen buyuk sayilarda.
        invented = [n for n in invented if len(n) > 1]
        if invented:
            dropped.append(f"{turn.speaker}: {turn.text[:60]}… (uydurma sayı: {', '.join(invented)})")
            continue
        kept.append(turn)
    return kept, dropped


def generate(bulletin: dict, config: dict | None = None) -> tuple[list[Turn], list[str]]:
    """Senaryoyu uret. (replikler, ayiklananlar) dondurur."""
    config = config or {}
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ScriptError("GEMINI_API_KEY tanimli degil")

    context, raw_sources = build_context(bulletin, int(config.get("max_items", 12)))
    if not raw_sources:
        raise ScriptError("Ozeti olan haber yok; senaryo uretilemez")

    # Sunucu adlari ve prompt dili ayardan gelir; aksi halde Ingilizce
    # bulten Turkce sunucularla ve Turkce metinle uretiliyordu.
    hosts = list(config.get("hosts") or ["AYŞE", "MERT"])
    language = config.get("language", "tr")
    rules = RULE_SETS.get(language, RULES_TR).format(a=hosts[0], b=hosts[1])

    if language == "en":
        task = (
            "Today's stories are below. Write one podcast episode script from them.\n"
            f"{context}\n\n"
            "Return JSON: an array of objects with \"speaker\" (either "
            f"\"{hosts[0]}\" or \"{hosts[1]}\") and \"text\"."
        )
    else:
        task = (
            "Bugünün haberleri aşağıda. Bunlardan bir podcast bölümü senaryosu yaz.\n"
            f"{context}\n\n"
            "Çıktıyı JSON olarak ver: her öğe {\"speaker\": "
            f"\"{hosts[0]}\" veya \"{hosts[1]}\", \"text\": \"replik\"}} biçiminde bir dizi."
        )

    prompt = f"{rules}\n\n{task}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(config.get("temperature", 0.4)),
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "speaker": {"type": "STRING", "enum": hosts},
                        "text": {"type": "STRING"},
                    },
                    "required": ["speaker", "text"],
                },
            },
        },
    }

    model = config.get("model", DEFAULT_MODEL)
    data = _post(
        GEMINI_URL.format(model=model),
        payload,
        {"x-goog-api-key": key, "Content-Type": "application/json"},
    )

    try:
        parsed = json.loads(data)
        text = parsed["candidates"][0]["content"]["parts"][0]["text"]
        items = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ScriptError(f"Senaryo ayristirilamadi: {data[:200]!r}") from exc

    turns = [
        Turn(speaker=i.get("speaker", hosts[0]), text=(i.get("text") or "").strip())
        for i in items
        if (i.get("text") or "").strip()
    ]
    return verify_turns(turns, raw_sources)
