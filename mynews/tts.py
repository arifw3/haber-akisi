# coding=utf-8
"""Seslendirme: her haber icin ayri ses dosyasi uretir.

Tasarim notu: bulteni tek uzun MP3'te birlestirmek yerine haber basina bir
dosya uretiyoruz. Boylece ffmpeg bagimliligi, cue senkronu ve uzun uretimde
kalite kaybi sorunlarinin ucu birden ortadan kalkiyor; PWA dosyalari sirayla
calarak ayni hands-free deneyimi veriyor, tek haber tekrar dinlenebiliyor.

Iki motor da opsiyoneldir. Anahtar yoksa PWA tarayicinin kendi Turkce sesini
(Web Speech API) kullanir, yani ses her halukarda calisir.

  ELEVENLABS_API_KEY  -> eleven  (POST /v1/text-to-speech/{voice_id})
  GEMINI_API_KEY      -> gemini  (gemini-2.5-flash-preview-tts, cok konusmacili)
  GOOGLE_TTS_API_KEY  -> google  (Cloud Text-to-Speech, Turkce anadil sesleri)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
GOOGLE_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"


class TTSError(RuntimeError):
    pass


@dataclass
class Clip:
    path: Path
    mime: str

    @property
    def suffix(self) -> str:
        return ".mp3" if "mpeg" in self.mime or "mp3" in self.mime else ".wav"


def _post(url: str, payload: dict, headers: dict, timeout: int = 120) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise TTSError(f"{url} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TTSError(f"{url} -> {exc}") from exc


# ----------------------------------------------------------------- ElevenLabs


def synth_eleven(text: str, out: Path, config: dict) -> Clip:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise TTSError("ELEVENLABS_API_KEY tanimli degil")

    voices = config.get("eleven_voices") or []
    if not voices:
        raise TTSError("config.tts.eleven_voices bos")

    # Her haberi tek bir ses okuyor. Sesler arasinda donusum yaparak
    # bulten monotonluktan cikiyor.
    voice_id = voices[hash(text) % len(voices)]

    audio = _post(
        ELEVEN_URL.format(voice_id=voice_id),
        {
            "text": text,
            "model_id": config.get("eleven_model", "eleven_multilingual_v2"),
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0},
        },
        {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    )
    out = out.with_suffix(".mp3")
    out.write_bytes(audio)
    return Clip(out, "audio/mpeg")


# --------------------------------------------------------------------- Gemini


def _pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    """Gemini ham L16 PCM donuyor; calinabilmesi icin WAV basligi sar."""
    block = channels * width
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, channels,
        rate, rate * block, block, width * 8, b"data", len(pcm),
    )
    return header + pcm


def synth_gemini(text: str, out: Path, config: dict) -> Clip:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise TTSError("GEMINI_API_KEY tanimli degil")

    model = config.get("gemini_model", "gemini-2.5-flash-preview-tts")
    voice = (config.get("gemini_voices") or ["Kore"])[0]

    data = _post(
        GEMINI_URL.format(model=model),
        {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
                },
            },
        },
        {"x-goog-api-key": key, "Content-Type": "application/json"},
    )

    try:
        parsed = json.loads(data)
        part = parsed["candidates"][0]["content"]["parts"][0]["inlineData"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise TTSError(f"Gemini yaniti beklenmedik bicimde: {data[:200]!r}") from exc

    pcm = base64.b64decode(part["data"])
    out = out.with_suffix(".wav")
    out.write_bytes(_pcm_to_wav(pcm))
    return Clip(out, "audio/wav")


# --------------------------------------------------- Google Cloud TTS


def synth_google(text: str, out: Path, config: dict) -> Clip:
    """Turkce anadil sesleri (tr-TR-Wavenet / Chirp3-HD).

    Aylik 1 milyon WaveNet karakteri ucretsiz katmanda; bultenin tamami
    (~143 bin/ay) bu sinirin altinda kaliyor.
    """
    key = os.environ.get("GOOGLE_TTS_API_KEY")
    if not key:
        raise TTSError("GOOGLE_TTS_API_KEY tanimli degil")

    voices = config.get("google_voices") or ["tr-TR-Wavenet-E"]
    voice = voices[hash(text) % len(voices)]

    data = _post(
        f"{GOOGLE_TTS_URL}?key={key}",
        {
            "input": {"text": text},
            "voice": {"languageCode": config.get("google_language", "tr-TR"), "name": voice},
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": float(config.get("google_rate", 1.0)),
                "pitch": float(config.get("google_pitch", 0.0)),
            },
        },
        {"Content-Type": "application/json"},
    )

    try:
        audio = base64.b64decode(json.loads(data)["audioContent"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise TTSError(f"Google TTS yaniti beklenmedik: {data[:200]!r}") from exc

    out = out.with_suffix(".mp3")
    out.write_bytes(audio)
    return Clip(out, "audio/mpeg")


ENGINES = {"eleven": synth_eleven, "gemini": synth_gemini, "google": synth_google}


def available_engine(preferred: str = "auto") -> str | None:
    """Anahtari tanimli olan ilk motoru sec. Yoksa None (tarayici sesi kullanilir)."""
    have = {
        "google": bool(os.environ.get("GOOGLE_TTS_API_KEY")),
        "eleven": bool(os.environ.get("ELEVENLABS_API_KEY")),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
    }
    if preferred in ENGINES:
        return preferred if have[preferred] else None
    # Turkce anadil sesleri oldugu ve ucretsiz katmani genis oldugu icin
    # otomatik secimde once Google denenir.
    for name in ("google", "eleven", "gemini"):
        if have[name]:
            return name
    return None


def cache_key(text: str, engine: str, config: dict) -> str:
    """Metin + motor + model + ses birlesimi icin kararli bir anahtar.

    Ses veya model degisirse anahtar da degisir; eski dosya yeniden
    kullanilmaz, dogru olan uretilir.
    """
    voices = config.get(f"{engine}_voices") or []
    model = config.get(f"{engine}_model", "")
    voice = voices[hash(text) % len(voices)] if voices else ""
    raw = "|".join([engine, model, voice, text])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _manifest_path(audio_dir: Path) -> Path:
    return audio_dir / "index.json"


def _load_manifest(audio_dir: Path) -> dict:
    path = _manifest_path(audio_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def prune_cache(audio_dir: Path, manifest: dict, retention_days: int) -> int:
    """Son N gundur kullanilmayan sesleri sil.

    Haber akisi her gun yenileniyor; dunun sesleri birikmeye devam ederse
    onbellek suresiz buyur. Ama hemen silmek de onbellegi anlamsiz kilar:
    gundemde kalan haber tekrar faturalanir. Bu yuzden "son kullanim"
    tarihine gore tutuyoruz.
    """
    if retention_days <= 0:
        return 0

    cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
    stale = [key for key, last_used in manifest.items() if last_used < cutoff]

    removed = 0
    for key in stale:
        for path in audio_dir.glob(key + ".*"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        manifest.pop(key, None)

    # Manifest'te izi kalmamis dosyalar (elle kopyalanmis, yarim kalmis)
    for path in audio_dir.iterdir():
        if path.name == "index.json" or not path.is_file():
            continue
        if path.stem not in manifest:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue

    return removed


def synthesize_bulletin(bulletin: dict, site_dir: Path, config: dict) -> int:
    """Bultendeki her habere ses uretir, item['audio'] alanini doldurur.

    Bir haber basarisiz olursa digerleri devam eder; o haber tarayici sesine
    duser. Toplam uretilen dosya sayisini dondurur.
    """
    engine_name = available_engine(config.get("engine", "auto"))
    if not engine_name:
        return 0

    engine = ENGINES[engine_name]

    # Icerik adresli onbellek: ayni metin + ses + model bir kez faturalanir.
    # Gundemde kalan haber ertesi gun, ayni gun ikinci build ise hic ucret
    # yaratmaz. Ziyaretci sayisi zaten maliyeti etkilemiyor - ses gunde bir
    # kez uretilip herkese ayni dosya sunuluyor.
    audio_dir = site_dir / "audio" / "cache"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Karakter kotasi sinirli: sadece en yuksek skorlu N habere ses uretilir,
    # kalanlari PWA'da tarayici sesiyle okunur. 0 = sinirsiz.
    items = [item for seg in bulletin["segments"] for item in seg["items"]]
    limit = int(config.get("limit", 0))
    if limit > 0:
        items = sorted(items, key=lambda i: i.get("score", 0), reverse=True)[:limit]

    manifest = _load_manifest(audio_dir)
    today = date.today().isoformat()

    produced = 0
    reused = 0
    spent = 0
    for item in items:
        key = cache_key(item["speech"], engine_name, config)
        manifest[key] = today
        existing = next(iter(audio_dir.glob(key + ".*")), None)
        if existing:
            item["audio"] = f"audio/cache/{existing.name}"
            reused += 1
            continue

        try:
            clip = engine(item["speech"], audio_dir / key, config)
        except TTSError as exc:
            print(f"  ses uretilemedi ({item['id']}): {exc}")
            continue
        item["audio"] = f"audio/cache/{clip.path.name}"
        produced += 1
        spent += len(item["speech"])

    removed = prune_cache(audio_dir, manifest, int(config.get("cache_days", 7)))
    _manifest_path(audio_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    bulletin["audio_engine"] = engine_name
    bulletin["audio_chars"] = spent
    bulletin["audio_reused"] = reused
    if reused:
        print(f"  {reused} ses onbellekten geldi (ucretsiz)")
    if removed:
        print(f"  {removed} eski ses dosyasi silindi")
    return produced

def synthesize_script(turns, site_dir: Path, config: dict, date: str) -> list[dict]:
    """Podcast repliklerini seslendirir; her sunucu kendi sesiyle konusur.

    Replikler ayri dosyalar halinde uretilir ve arayuz sirayla calar -
    boylece ffmpeg ile birlestirmeye gerek kalmaz, tek replik tekrar
    dinlenebilir ve onbellek replik bazinda calisir.
    """
    engine_name = available_engine(config.get("engine", "auto"))
    if not engine_name:
        return []

    engine = ENGINES[engine_name]
    audio_dir = site_dir / "audio" / "cache"
    audio_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(audio_dir)
    today = date

    voices = config.get("podcast_voices", {})
    out: list[dict] = []

    for turn in turns:
        # Konusmaciya gore ses secimi: cache_key ile tutarli olmasi icin
        # ayni ses listesi tek elemanli olarak veriliyor.
        voice = voices.get(turn.speaker)
        turn_config = dict(config)
        if voice:
            turn_config[f"{engine_name}_voices"] = [voice]

        key = cache_key(turn.text, engine_name, turn_config)
        manifest[key] = today
        existing = next(iter(audio_dir.glob(key + ".*")), None)

        if existing:
            path = existing
        else:
            try:
                path = engine(turn.text, audio_dir / key, turn_config).path
            except TTSError as exc:
                print(f"  replik seslendirilemedi: {exc}")
                continue

        out.append({
            "speaker": turn.speaker,
            "text": turn.text,
            "audio": f"audio/cache/{path.name}",
        })

    _manifest_path(audio_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out
