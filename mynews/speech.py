# coding=utf-8
"""Seslendirme metnini Turkce icin dogallastirir.

TTS motoru ne verirsen onu okur. Haber baslıkları yazili dil icin yazilmis:
kisaltmalar, tirnaklar, ust uste iki nokta, alan adlari. Bunlar okundugunda
yapay duyuluyor. Burasi metni sese uygun hale getirir.

En buyuk kazanc kisaltmalarda: "AKP" harfi harfine okunmali ("A Ka Pe"),
ama "MASAK" kelime gibi okunur. Ikisini ayirt eden bir liste tutuyoruz.
"""
from __future__ import annotations

import re

# Turkce'de harf harf okunan kisaltmalar -> okunusu
SPELLED = {
    "AKP": "A Ka Pe",
    "CHP": "Ce He Pe",
    "MHP": "Me He Pe",
    "HDP": "He De Pe",
    "DEVA": "Deva",
    "TBMM": "Te Be Em Me",
    "ABD": "A Be De",
    "AB": "A Be",
    "BM": "Be Em",
    "İBB": "İ Be Be",
    "ABB": "A Be Be",
    "TFF": "Te Fe Fe",
    "YSK": "Ye Se Ka",
    "TSK": "Te Se Ka",
    "PKK": "Pe Ke Ke",
    "MSB": "Me Se Be",
    "SGK": "Se Ge Ka",
    "TCMB": "Te Ce Em Be",
    "KKTC": "Ka Ka Te Ce",
    "AFAD": "Afad",
    "THY": "Te He Ye",
    "OECD": "O E Ce De",
    "IMF": "İ Em Ef",
    "AİHM": "A İ He Me",
    "TRT": "Te Re Te",
    "CHP'li": "Ce He Pe'li",
    "AKP'li": "A Ka Pe'li",
}

# Kelime gibi okunanlar: dokunmuyoruz (MASAK, NATO, TUIK, MIT, DEM...)
PRONOUNCED = {
    "MASAK", "NATO", "UEFA", "FIFA", "TÜİK", "MİT", "DEM", "İYİ", "MEB",
    "ASELSAN", "TÜBİTAK", "TOKİ", "İETT", "SPK", "BDDK", "YÖK", "OHAL",
    "PISA", "NASA", "WHO", "UNESCO", "EURO", "VAR", "MEB", "TEOG", "LGS", "YKS",
}

# Rakam iceren yayinci adlari: "T24" -> "Te yirmi dört"
PUBLISHER_SPEECH = {
    "T24": "Te yirmi dört",
    "CNN Türk": "Si En En Türk",
    "NTV": "En Te Ve",
    "NTVSpor": "En Te Ve Spor",
    "TRT Haber": "Te Re Te Haber",
    "TRTSpor": "Te Re Te Spor",
    "A Spor": "A Spor",
    "beIN SPORTS": "biin sports",
    "Bloomberght": "Bloomberg Ha Te",
    "DHA": "De He A",
    "AA": "A A",
}

_ABBR_RE = re.compile(r"\b([A-ZÇĞİÖŞÜ]{2,})(['’][a-zçğıöşü]+)?\b")
_QUOTES = dict.fromkeys(map(ord, '"“”«»'), None)
# Kelime icindeki apostrof ek ayiricidir, korunur; disardakiler tirnaktir.
_APOSTROPHE_RE = re.compile(r"(?<![\w])['’]|['’](?![\w])")
_DOMAIN_RE = re.compile(r"\b([\w-]+)\.(?:net|com|org|tr|com\.tr)\b", re.I)


def expand_abbreviations(text: str) -> str:
    """Harf harf okunan kisaltmalari okunusuyla degistir."""

    def repl(match: re.Match) -> str:
        word, suffix = match.group(1), match.group(2) or ""
        if word in PRONOUNCED:
            return word + suffix
        if word in SPELLED:
            # Eki bosluklu birak: "Ce He Peli" degil "Ce He Pe li"
            return SPELLED[word] + (" " + suffix.lstrip("'’") if suffix else "")
        # Listede yoksa ve kisaysa harflere ayirmak yerine oldugu gibi birak:
        # yanlis okumak, bilmedigimiz bir kisaltmayi bozmaktan iyidir.
        return word + suffix

    return _ABBR_RE.sub(repl, text)


def clean_for_speech(text: str) -> str:
    """Yazili dile ait isaretleri sesli okuma icin sadelestir."""
    # Alan adi yayinci adi olarak geliyor: "birgun.net" -> "birgun"
    text = _DOMAIN_RE.sub(lambda m: m.group(1), text)

    text = text.translate(_QUOTES)          # tirnaklar okunmaz, duraklama yaratir
    text = _APOSTROPHE_RE.sub("", text)    # tirnak gorevindeki apostroflar
    # Haber basliklarindaki "Kim: ne dedi" kalibi. Iki nokta TTS'te duraklama
    # yaratmiyor, cumleler birbirine giriyordu; virgul dogru tonlamayi veriyor.
    text = re.sub(r"\s*:\s*", ", ", text)
    text = text.replace(";", ".")           # noktali virgul TTS'te belirsiz
    text = text.replace(" - ", ", ")
    # (ÖZET), (VİDEO) gibi editoryal etiketler okunmamali
    text = re.sub(r"\((?:ÖZET|VİDEO|VIDEO|FOTO|FOTOĞRAF|CANLI|GALERİ)\)", "", text, flags=re.I)
    text = re.sub(r"\.{2,}", ".", text)     # "..." tek noktaya
    text = re.sub(r"!+", ".", text)         # haber metninde unlem yapay duyuluyor
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,])", r"\1", text)
    return text.strip()


def normalize(text: str, rules: str = "tr") -> str:
    """Metni seslendirmeye hazir hale getir.

    Kisaltma acilimlari Turkce'ye ozgudur ("AKP" -> "A Ka Pe"); baska
    dillerde uygulanmaz, cunku o dillerin TTS'i kendi kurallariyla okur.
    Noktalama sadelestirmesi ise dilden bagimsizdir.
    """
    if rules == "tr":
        text = expand_abbreviations(text)
    return clean_for_speech(text)


def intro_for(publisher: str, rules: str = "tr") -> str:
    """Yayinci adini cumle basi olarak dogal bicimde ver.

    Iki nokta ust uste yerine nokta kullaniyoruz: TTS iki noktada
    duraklamiyor, cumleler birbirine giriyordu.
    """
    name = (publisher or "").strip()
    if name in PUBLISHER_SPEECH:
        return PUBLISHER_SPEECH[name]
    name = _DOMAIN_RE.sub(lambda m: m.group(1), name)
    return normalize(name, rules).rstrip(".:")
