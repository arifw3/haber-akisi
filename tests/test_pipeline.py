# coding=utf-8
"""Boru hattinin ag erisimi gerektirmeyen birim testleri.

Fixture'lar gercek Google News RSS ciktisindan alinmis yapidadir.
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mynews.gnews import NewsItem, Related, parse_feed, parse_related, split_title
from mynews.images import ImageResolver, extract_image, parse_articles
from mynews.rank import Ranker, normalize, similarity

NOW = datetime.now(timezone.utc)

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Türkiye - Google Haberler</title>
<item>
  <title>Ankara'da önemli bir gelişme yaşandı - Hürriyet</title>
  <link>https://news.google.com/rss/articles/CBMiABC?oc=5</link>
  <guid isPermaLink="false">CBMiABC</guid>
  <pubDate>{fresh}</pubDate>
  <description>&lt;ol&gt;&lt;li&gt;&lt;a href="https://news.google.com/x"&gt;Ankara'da gelişme&lt;/a&gt;
    &lt;font color="#6f6f6f"&gt;Cumhuriyet&lt;/font&gt;&lt;/li&gt;
    &lt;li&gt;&lt;a href="https://news.google.com/y"&gt;Başkentte hareketli saatler&lt;/a&gt;
    &lt;font color="#6f6f6f"&gt;TRT Haber&lt;/font&gt;&lt;/li&gt;&lt;/ol&gt;</description>
  <source url="https://www.hurriyet.com.tr">Hürriyet</source>
</item>
<item>
  <title>Canlı Anlatım: Göztepe Gaziantep FK (Süper Lig maçı) - Hürriyet</title>
  <link>https://news.google.com/rss/articles/CBMiDEF?oc=5</link>
  <guid isPermaLink="false">CBMiDEF</guid>
  <pubDate>{fresh}</pubDate>
  <description></description>
  <source url="https://www.hurriyet.com.tr">Hürriyet</source>
</item>
</channel></rss>
"""


def rss_date(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def make_item(title, publisher="Hürriyet", hours=2, related=0, url="https://www.hurriyet.com.tr"):
    return NewsItem(
        id=title,
        title=title,
        publisher=publisher,
        publisher_url=url,
        published=NOW - timedelta(hours=hours),
        link="https://news.google.com/rss/articles/X",
        category="turkiye",
        related=[Related(title=f"{title} varyant {i}", source=f"Kaynak{i}") for i in range(related)],
    )


class TestParsing(unittest.TestCase):
    def test_split_title_strips_publisher(self):
        self.assertEqual(
            split_title("Bir olay oldu - Hürriyet"), ("Bir olay oldu", "Hürriyet")
        )

    def test_split_title_uses_last_separator(self):
        self.assertEqual(split_title("A - B - Sözcü"), ("A - B", "Sözcü"))

    def test_split_title_without_separator(self):
        self.assertEqual(split_title("Ayırıcı yok"), ("Ayırıcı yok", ""))

    def test_long_tail_is_not_a_publisher(self):
        # 40 karakterden uzun son parca yayinci degil, basligin kendisidir.
        title = "Şu oldu - bu çok uzun bir cümledir ve yayıncı adı olamaz kesinlikle"
        self.assertEqual(split_title(title)[1], "")

    def test_parse_related_extracts_source_and_title(self):
        feed = FEED.format(fresh=rss_date(NOW))
        items = parse_feed(feed.encode("utf-8"), "turkiye")
        first = items[0]
        self.assertEqual(len(first.related), 2)
        self.assertEqual(first.related[1].source, "TRT Haber")
        self.assertEqual(first.related[0].title, "Ankara'da gelişme")

    def test_parse_feed_reads_publisher_domain(self):
        items = parse_feed(FEED.format(fresh=rss_date(NOW)).encode("utf-8"), "turkiye")
        self.assertEqual(items[0].domain, "hurriyet.com.tr")
        self.assertEqual(items[0].publisher, "Hürriyet")

    def test_source_count_counts_distinct_publishers(self):
        items = parse_feed(FEED.format(fresh=rss_date(NOW)).encode("utf-8"), "turkiye")
        # Hurriyet + Cumhuriyet + TRT Haber
        self.assertEqual(items[0].source_count, 3)

    def test_empty_description_yields_no_related(self):
        self.assertEqual(parse_related(""), [])


class TestNormalisation(unittest.TestCase):
    def test_turkish_dotted_capital_i(self):
        # Varsayilan lower() 'I' -> 'i' yapmaz; Turkce esleme sart.
        self.assertEqual(normalize("İSTANBUL"), "istanbul")
        self.assertEqual(normalize("IĞDIR"), "iğdir")

    def test_similarity_matches_same_event(self):
        a = "Melih Gökçek'in oğlu adli kontrolle serbest bırakıldı"
        b = "Melih Gökçek'in oğlu hakkında adli kontrol kararı"
        self.assertGreater(similarity(a, b), 0.3)

    def test_similarity_separates_events(self):
        self.assertLess(
            similarity("Fenerbahçe transferi bitirdi", "Bilim insanları yeni gezegen buldu"),
            0.1,
        )


class TestRanking(unittest.TestCase):
    def setUp(self):
        self.ranker = Ranker()

    def test_live_match_commentary_dropped(self):
        item = make_item("Canlı Anlatım: Göztepe Gaziantep FK (Süper Lig maçı)")
        self.assertTrue(self.ranker.score(item).dropped)

    def test_stale_item_dropped(self):
        self.assertTrue(self.ranker.score(make_item("Eski haber", hours=200)).dropped)

    def test_multi_source_outranks_single_source(self):
        multi = self.ranker.score(make_item("Gündemde büyük gelişme", related=4))
        single = self.ranker.score(make_item("Gündemde başka gelişme", related=0))
        self.assertGreater(multi.score, single.score)

    def test_clickbait_penalised(self):
        plain = self.ranker.score(make_item("Bakanlık yeni düzenlemeyi açıkladı"))
        bait = self.ranker.score(make_item("ŞOK! Dünyanın sonu için sayılı gün kaldı!"))
        self.assertGreater(plain.score, bait.score)
        self.assertGreater(bait.clickbait, 0)

    def test_publisher_cap_enforced(self):
        items = [make_item(f"Farklı bir haber numara {i}", related=3) for i in range(8)]
        chosen = self.ranker.select(items, 8)
        self.assertLessEqual(len(chosen), int(self.ranker.s["max_per_publisher"]))

    def test_near_duplicate_titles_collapse(self):
        items = [
            make_item("Ankara'da trafik kazası meydana geldi", publisher="Hürriyet", related=3),
            make_item("Ankara'da trafik kazası meydana geldi bugün", publisher="TRT Haber", related=3),
            make_item("Yeni ekonomi paketi açıklandı", publisher="NTV", related=3),
        ]
        chosen = self.ranker.select(items, 10)
        self.assertEqual(len(chosen), 2)

    def test_segment_override_changes_weights(self):
        base = Ranker()
        tuned = Ranker(segment={"scoring_override": {"w_trust": 3.0}})
        self.assertGreater(float(tuned.s["w_trust"]), float(base.s["w_trust"]))

    def test_min_trust_filters_content_farms(self):
        ranker = Ranker(segment={"min_trust": 0.5})
        low = make_item("Bir haber", publisher="Onedio")
        self.assertTrue(ranker.score(low).dropped)


class TestSpeech(unittest.TestCase):
    def test_speech_mentions_publisher_and_source_count(self):
        from mynews.build import speech_text

        text = speech_text(make_item("Önemli bir gelişme", related=4))
        self.assertIn("Hürriyet", text)
        self.assertIn("5 ayrı kaynak", text)

    def test_speech_skips_count_for_single_source(self):
        from mynews.build import speech_text

        self.assertNotIn("ayrı kaynak", speech_text(make_item("Tek kaynaklı haber")))

    def test_columnist_headline_not_used_as_context(self):
        from mynews.build import pick_extra

        item = make_item("Seçim tartışması büyüyor")
        item.related = [Related(title="Seçimin ucu göründü | Ali Veli Köşe Yazısı", source="X")]
        self.assertEqual(pick_extra(item), "")


PUB_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
<item>
  <title>Ankara'da onemli bir gelisme yasandi</title>
  <link>https://www.hurriyet.com.tr/gundem/haber-123</link>
  <media:content url="https://image.hurimg.com/foto.jpg"/>
</item>
<item>
  <title>Bambaska bir konu hakkinda haber</title>
  <link>https://www.hurriyet.com.tr/gundem/haber-456</link>
  <enclosure url="https://image.hurimg.com/diger.jpg" type="image/jpeg"/>
</item>
</channel></rss>"""


class TestImageExtraction(unittest.TestCase):
    def test_parses_media_content(self):
        articles = parse_articles(PUB_FEED)
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].image, "https://image.hurimg.com/foto.jpg")

    def test_parses_enclosure(self):
        self.assertEqual(parse_articles(PUB_FEED)[1].image, "https://image.hurimg.com/diger.jpg")

    def test_parses_body_img_tag(self):
        feed = b"""<rss><channel><item>
          <title>Baslik</title><link>https://x.com/a</link>
          <description>&lt;p&gt;&lt;img src="https://x.com/resim.jpg"&gt;metin&lt;/p&gt;</description>
        </item></channel></rss>"""
        self.assertEqual(parse_articles(feed)[0].image, "https://x.com/resim.jpg")

    def test_non_image_enclosure_ignored(self):
        item = ET.fromstring('<item><enclosure url="https://x.com/a.mp3" type="audio/mpeg"/></item>')
        self.assertEqual(extract_image(item), "")

    def test_recovers_from_malformed_xml(self):
        # Yayinci feed'lerinde yaygin: BOM ve kacak & isareti
        broken = "﻿<rss><channel><item><title>A & B</title>"                  "<link>https://x.com/a</link></item></channel></rss>"
        articles = parse_articles(broken.encode("utf-8"))
        self.assertEqual(len(articles), 1)

    def test_items_without_link_skipped(self):
        feed = b"<rss><channel><item><title>Basliksiz link</title></item></channel></rss>"
        self.assertEqual(parse_articles(feed), [])


class TestImageResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = ImageResolver({"hurriyet.com.tr": []}, threshold=0.5)
        self.resolver._cache["hurriyet.com.tr"] = parse_articles(PUB_FEED)

    def test_matches_same_story(self):
        match = self.resolver.resolve("Ankara'da onemli bir gelisme yasandi", "hurriyet.com.tr")
        self.assertIsNotNone(match)
        self.assertEqual(match.image, "https://image.hurimg.com/foto.jpg")

    def test_rejects_unrelated_story(self):
        # Yanlis eslesme yanlis gorsel demektir; esik altinda kalmali.
        self.assertIsNone(self.resolver.resolve("Fenerbahce transferi bitirdi", "hurriyet.com.tr"))

    def test_unknown_domain_returns_none(self):
        self.assertIsNone(self.resolver.resolve("Herhangi bir baslik", "bilinmeyen.com"))

    def test_stats_track_coverage(self):
        self.resolver.resolve("Ankara'da onemli bir gelisme yasandi", "hurriyet.com.tr")
        self.resolver.resolve("Alakasiz bir baslik burada", "hurriyet.com.tr")
        self.assertEqual(self.resolver.stats["aranan"], 2)
        self.assertEqual(self.resolver.stats["eslesen"], 1)
        self.assertEqual(self.resolver.stats["gorselli"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
