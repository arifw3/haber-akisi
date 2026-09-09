# coding=utf-8
"""Komut satiri arayuzu.

  python -m mynews health            feed sagligi
  python -m mynews rank --explain    secim ve skor kirilimi
  python -m mynews build             site/data/latest.json uret
"""
from __future__ import annotations

import argparse
import json
import sys

from .build import build, write
from .digest import write as write_digest
from .gnews import check_feed
from .rank import Ranker, load_config
from .tts import available_engine, synthesize_bulletin


def cmd_health(_: argparse.Namespace) -> int:
    cfg = load_config()
    bad = 0
    for seg in cfg["segments"]:
        for topic in seg["topics"]:
            report, _items = check_feed(topic, seg["key"])
            age = (
                f"{report.newest_age_hours:.1f}s"
                if report.newest_age_hours is not None
                else "-"
            )
            print(
                f"{topic:<12} {report.status:<7} n={report.count:<4} en_yeni={age:<8}"
                f"{report.error}"
            )
            if report.status != "ok":
                bad += 1
    print("\nTumu saglikli." if not bad else f"\n{bad} feed sorunlu.")
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    cfg = load_config()
    ranker = Ranker(cfg)
    for seg in cfg["segments"]:
        pool = []
        for topic in seg["topics"]:
            _report, items = check_feed(topic, seg["key"])
            pool.extend(items)
        chosen = ranker.select(pool, int(seg["limit"]))
        print(f"\n=== {seg['title']} ({len(chosen)}/{len(pool)}) ===")
        for rank, s in enumerate(chosen, 1):
            print(f"{rank:>2}. {s.item.title[:72]}")
            print(
                f"     {s.item.publisher[:20]:<20} skor={s.score:.2f}  "
                f"kaynak={s.item.source_count} taze={s.freshness:.2f} "
                f"guven={s.trust:.2f} bait={s.clickbait:.2f}"
            )
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    cfg = load_config()
    bulletin = build(cfg)

    if args.with_audio:
        from pathlib import Path

        tts_cfg = cfg.get("tts", {})
        engine = available_engine(tts_cfg.get("engine", "auto"))
        if not engine:
            print("Ses motoru anahtari yok; PWA tarayici sesini kullanacak.")
        else:
            site = Path(__file__).resolve().parent.parent / "site"
            count = synthesize_bulletin(bulletin, site, tts_cfg)
            print(f"{engine} ile {count} ses dosyasi uretildi.")

    if args.podcast:
        from pathlib import Path

        from .script import ScriptError, generate
        from .tts import synthesize_script

        try:
            turns, dropped = generate(bulletin, cfg.get("podcast", {}))
            print(f"Senaryo: {len(turns)} replik.")
            for line in dropped:
                print(f"  ayiklandi -> {line}")

            site = Path(__file__).resolve().parent.parent / "site"
            segments = synthesize_script(turns, site, cfg.get("tts", {}), bulletin["date"])
            bulletin["podcast"] = {
                "date": bulletin["date"],
                "turns": segments,
                "dropped": len(dropped),
            }
            print(f"Podcast: {len(segments)} replik seslendirildi.")

            # Podcast uygulamalari tek dosya bekler: replikleri birlestirip
            # bolumu arsive ekle ve RSS'i yenile.
            from .podcast import build_episode, load_episodes, write_feed

            pod_cfg = cfg.get("podcast", {})
            episode = build_episode(bulletin, site, int(pod_cfg.get("keep", 30)))
            if episode:
                base = pod_cfg.get("base_url", "")
                feed = write_feed(load_episodes(site / "data" / "episodes.json"), site, base, pod_cfg)
                bulletin["episode"] = episode
                print(
                    f"Bolum: {episode['audio']} "
                    f"({episode['bytes'] // 1024} KB, {episode['duration'] // 60}:{episode['duration'] % 60:02d}) "
                    f"-> {feed.name}"
                )
        except ScriptError as exc:
            print(f"Podcast uretilemedi: {exc}")

    paths = write(bulletin) + write_digest(bulletin)

    if args.sync_doc:
        from .digest import render_text
        from .gdocs import DocSyncError, service_account_email, sync_document

        try:
            written = sync_document(render_text(bulletin))
            print(f"Google Doc guncellendi ({written} karakter).")
        except DocSyncError as exc:
            print(f"Doc senkronu basarisiz: {exc}")
            email = service_account_email()
            if email:
                print(f"  servis hesabi: {email}")

    for seg in bulletin["segments"]:
        print(f"{seg['title']:<20} {len(seg['items']):>2} haber")
    problems = [h for h in bulletin["health"] if h["status"] != "ok"]
    if problems:
        print("\nUYARI - sorunlu feed:")
        for p in problems:
            print(f"  {p['topic']}: {p['status']} {p['error']}")
    print(f"\nToplam {bulletin['total']} haber ->")
    for p in paths:
        print(f"  {p}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Yayinlanan (veya yereldeki) bulteni denetle."""
    import io as _io
    from pathlib import Path

    from .doctor import fetch_bulletin, inspect

    cfg = load_config()
    if args.url:
        print(f"Denetlenen: {args.url}")
        bulletin = fetch_bulletin(args.url)
    else:
        path = Path(__file__).resolve().parent.parent / "site" / "data" / "latest.json"
        print(f"Denetlenen: {path}")
        bulletin = json.loads(_io.open(path, encoding="utf-8").read())

    report = inspect(bulletin, cfg.get("thresholds", {}))
    print(report.render())
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mynews")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="feed sagligini kontrol et").set_defaults(fn=cmd_health)
    p_rank = sub.add_parser("rank", help="secimi ve skorlari goster")
    p_rank.add_argument("--explain", action="store_true")
    p_rank.set_defaults(fn=cmd_rank)
    p_build = sub.add_parser("build", help="site/data/latest.json uret")
    p_build.add_argument(
        "--with-audio",
        action="store_true",
        help="ses anahtari tanimliysa haber basina ses uret",
    )
    p_build.add_argument(
        "--podcast",
        action="store_true",
        help="GEMINI_API_KEY varsa iki sunuculu podcast senaryosu uret ve seslendir",
    )
    p_build.add_argument(
        "--sync-doc",
        action="store_true",
        help="bulteni GOOGLE_DOC_ID ile belirtilen Google Doc'a yaz (NotebookLM icin)",
    )
    p_build.set_defaults(fn=cmd_build)

    p_doctor = sub.add_parser("doctor", help="bulteni esiklere gore denetle")
    p_doctor.add_argument("--url", default="", help="canli site adresi (bos ise yerel dosya)")
    p_doctor.set_defaults(fn=cmd_doctor)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
