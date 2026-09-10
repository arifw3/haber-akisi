# coding=utf-8
"""Bulteni duz metin olarak yazar.

Iki isi var:

1. Sitedeki PWA JavaScript ile calisiyor; tarayici olmayan okuyucular
   (NotebookLM, arama motorlari, RSS okuyuculari) icerigi goremiyor.
2. NotebookLM Google Docs kaynaklarini otomatik senkronluyor. Gunluk
   bulteni duz metin olarak uretirsek bir Doc'a yazip kaynak gosterebiliyoruz.

Cikti bilerek sade: baslik, yayinci, kac kaynak yazdi, ozet ve bağlantı.
Uydurma yok - elimizde ne varsa o.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

# Turkce buyuk harf: varsayilan upper() "i" -> "I" yapiyor, "İ" olmali.
_TR_UPPER = str.maketrans("iı", "İI")


def tr_upper(text: str) -> str:
    return text.translate(_TR_UPPER).upper()


ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"


def _format_date(iso: str) -> str:
    aylar = [
        "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
        "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
    ]
    try:
        dt = datetime.fromisoformat(iso)
        return f"{dt.day} {aylar[dt.month - 1]} {dt.year}"
    except (ValueError, IndexError):
        return iso


def render_text(bulletin: dict) -> str:
    """NotebookLM ve okuyucular icin duz metin bulten."""
    lines: list[str] = []
    tarih = _format_date(bulletin.get("generated_at", ""))

    lines.append(f"HABER AKIŞI — {tarih}")
    lines.append("")
    lines.append(
        "Google Haberler RSS akışlarından derlenmiştir. Bir olayı kaç farklı "
        "yayıncının yazdığı önem sinyali olarak kullanılır. Özetler haber "
        "başlıklarıyla sınırlıdır; makale gövdesi kaynakta yer alır."
    )
    lines.append("")

    for segment in bulletin.get("segments", []):
        lines.append("=" * 60)
        lines.append(tr_upper(segment["title"]))
        lines.append("=" * 60)
        lines.append("")

        for index, item in enumerate(segment.get("items", []), 1):
            lines.append(f"{index}. {item['title']}")
            kaynak = f"   Kaynak: {item['publisher']}"
            if item.get("source_count", 0) >= 3:
                kaynak += f" (bu olayı {item['source_count']} yayıncı yazdı)"
            lines.append(kaynak)

            if item.get("speech"):
                lines.append(f"   Özet: {item['speech']}")

            for related in item.get("related", [])[:3]:
                lines.append(f"   - {related['source']}: {related['title']}")

            lines.append(f"   Bağlantı: {item.get('source_url') or item.get('link', '')}")
            lines.append("")

    lines.append("=" * 60)
    lines.append(f"Toplam {bulletin.get('total', 0)} haber.")
    lines.append("Kaynak: https://arifw3.github.io/haber-akisi/")
    return "\n".join(lines)


def render_html(bulletin: dict) -> str:
    """Tarayicisiz okunabilen basit HTML - JS gerektirmez."""
    tarih = _format_date(bulletin.get("generated_at", ""))
    parts = [
        "<!DOCTYPE html>",
        '<html lang="tr"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>Haber Akışı — {tarih}</title>",
        "<style>body{max-width:44rem;margin:2rem auto;padding:0 1.2rem;"
        "font:16px/1.6 system-ui,sans-serif;color:#2a1020}"
        "h1{font-size:1.6rem}h2{margin-top:2.4rem;border-bottom:2px solid #ffc4dc;padding-bottom:.3rem}"
        "article{margin:1.4rem 0}h3{margin:0 0 .3rem;font-size:1.05rem}"
        ".meta{color:#7b5164;font-size:.9rem}ul{margin:.4rem 0;padding-left:1.1rem;color:#7b5164;font-size:.92rem}"
        "a{color:#d81b60}</style></head><body>",
        f"<h1>Haber Akışı — {tarih}</h1>",
        "<p class='meta'>Google Haberler RSS akışlarından derlenmiştir. "
        "Bir olayı kaç yayıncının yazdığı önem sinyali olarak kullanılır.</p>",
    ]

    for segment in bulletin.get("segments", []):
        parts.append(f"<h2>{_esc(segment['title'])}</h2>")
        for item in segment.get("items", []):
            url = item.get("source_url") or item.get("link", "")
            parts.append("<article>")
            parts.append(f'<h3><a href="{_esc(url)}">{_esc(item["title"])}</a></h3>')
            meta = _esc(item["publisher"])
            if item.get("source_count", 0) >= 3:
                meta += f" · {item['source_count']} kaynak"
            parts.append(f'<p class="meta">{meta}</p>')
            if item.get("speech"):
                parts.append(f"<p>{_esc(item['speech'])}</p>")
            related = item.get("related", [])[:3]
            if related:
                parts.append("<ul>")
                for rel in related:
                    parts.append(f"<li>{_esc(rel['source'])}: {_esc(rel['title'])}</li>")
                parts.append("</ul>")
            parts.append("</article>")

    parts.append(f"<p class='meta'>Toplam {bulletin.get('total', 0)} haber.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write(bulletin: dict, site_dir: Path = SITE_DIR) -> list[Path]:
    site_dir.mkdir(parents=True, exist_ok=True)
    locale = bulletin.get("locale", "tr")
    paths = [site_dir / f"bulten-{locale}.txt", site_dir / f"bulten-{locale}.html"]
    paths[0].write_text(render_text(bulletin), encoding="utf-8")
    paths[1].write_text(render_html(bulletin), encoding="utf-8")
    return paths
