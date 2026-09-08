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
"""
from __future__ import annotations

import base64
import json
import os
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


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


ENGINES = {"eleven": synth_eleven, "gemini": synth_gemini}


def available_engine(preferred: str = "auto") -> str | None:
    """Anahtari tanimli olan ilk motoru sec. Yoksa None (tarayici sesi kullanilir)."""
    have = {
        "eleven": bool(os.environ.get("ELEVENLABS_API_KEY")),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
    }
    if preferred in ENGINES:
        return preferred if have[preferred] else None
    for name in ("eleven", "gemini"):
        if have[name]:
            return name
    return None


def synthesize_bulletin(bulletin: dict, site_dir: Path, config: dict) -> int:
    """Bultendeki her habere ses uretir, item['audio'] alanini doldurur.

    Bir haber basarisiz olursa digerleri devam eder; o haber tarayici sesine
    duser. Toplam uretilen dosya sayisini dondurur.
    """
    engine_name = available_engine(config.get("engine", "auto"))
    if not engine_name:
        return 0

    engine = ENGINES[engine_name]
    audio_dir = site_dir / "audio" / bulletin["date"]
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Karakter kotasi sinirli: sadece en yuksek skorlu N habere ses uretilir,
    # kalanlari PWA'da tarayici sesiyle okunur. 0 = sinirsiz.
    items = [item for seg in bulletin["segments"] for item in seg["items"]]
    limit = int(config.get("limit", 0))
    if limit > 0:
        items = sorted(items, key=lambda i: i.get("score", 0), reverse=True)[:limit]

    produced = 0
    spent = 0
    for item in items:
        target = audio_dir / item["id"]
        try:
            clip = engine(item["speech"], target, config)
        except TTSError as exc:
            print(f"  ses uretilemedi ({item['id']}): {exc}")
            continue
        item["audio"] = f"audio/{bulletin['date']}/{clip.path.name}"
        produced += 1
        spent += len(item["speech"])

    bulletin["audio_engine"] = engine_name
    bulletin["audio_chars"] = spent
    return produced
