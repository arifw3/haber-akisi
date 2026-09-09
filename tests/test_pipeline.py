# coding=utf-8
"""Boru hattinin ag erisimi gerektirmeyen birim testleri.

Fixture'lar gercek Google News RSS ciktisindan alinmis yapidadir.
"""
import json
import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mynews.gnews import NewsItem, Related, parse_feed, parse_related, split_title
from mynews.digest import render_html, render_text, tr_upper
from mynews.gdocs import DocSyncError, _document_end_index, service_account_email
from mynews.images import ImageResolver, extract_image, extract_summary, parse_articles
from mynews.script import Turn, build_context, verify_turns
from mynews.rank import Ranker, normalize, similarity
from mynews.speech import intro_for, normalize as speech_normalize

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


class TestSpeechNormalisation(unittest.TestCase):
    def test_spelled_abbreviations_expanded(self):
        text = speech_normalize("AKP ve CHP arasında gerginlik")
        self.assertIn("A Ka Pe", text)
        self.assertIn("Ce He Pe", text)

    def test_suffix_kept_separate(self):
        # "Ce He Peli" degil "Ce He Pe li" okunmali
        self.assertIn("Ce He Pe li", speech_normalize("CHP'li başkan"))

    def test_word_like_abbreviations_untouched(self):
        for word in ("MASAK", "NATO", "PISA", "TÜİK"):
            self.assertIn(word, speech_normalize(f"{word} raporu yayımlandı"))

    def test_unknown_abbreviation_left_alone(self):
        # Bilmedigimiz kisaltmayi bozmaktansa oldugu gibi birak
        self.assertIn("XYZK", speech_normalize("XYZK kurumu açıklama yaptı"))

    def test_colon_becomes_comma(self):
        # Iki nokta TTS'te duraklama yaratmiyor
        out = speech_normalize("Bakan Tekin: Türkiye puanını artırdı")
        self.assertNotIn(":", out)
        self.assertIn("Bakan Tekin, Türkiye", out)

    def test_quotes_removed_but_apostrophe_kept(self):
        out = speech_normalize("Camide 'yardım parası' kavgası Ankara'da büyüdü")
        self.assertNotIn("'yardım", out)
        self.assertIn("Ankara'da", out)

    def test_editorial_tags_stripped(self):
        self.assertNotIn("ÖZET", speech_normalize("Villa 3 puanla başladı (ÖZET)"))

    def test_exclamation_softened(self):
        self.assertNotIn("!", speech_normalize("Kırmızı bayrak çekildi!"))

    def test_publisher_pronunciation(self):
        self.assertEqual(intro_for("T24"), "Te yirmi dört")
        self.assertEqual(intro_for("Bloomberght"), "Bloomberg Ha Te")

    def test_domain_publisher_cleaned(self):
        # "birgun.net" -> "birgun nokta net" diye okunmamali
        self.assertNotIn(".", intro_for("birgun.net"))


BULLETIN = {
    "generated_at": "2026-09-09T06:00:00+00:00",
    "total": 1,
    "segments": [{
        "key": "turkiye", "title": "Türkiye",
        "items": [{
            "title": "Ankara'da gelişme", "publisher": "Hürriyet", "source_count": 5,
            "speech": "Hürriyet. Ankara'da gelişme.", "link": "https://news.google.com/x",
            "source_url": "https://www.hurriyet.com.tr/haber-1",
            "related": [{"source": "TRT Haber", "title": "Başkentte hareketlilik"}],
        }],
    }],
}


class TestDigest(unittest.TestCase):
    def test_turkish_uppercase(self):
        # Varsayilan upper() "Türkiye" -> "TÜRKIYE" yapar; dogrusu "TÜRKİYE"
        self.assertEqual(tr_upper("Türkiye"), "TÜRKİYE")
        self.assertEqual(tr_upper("Bilim"), "BİLİM")

    def test_text_contains_headline_and_publisher(self):
        out = render_text(BULLETIN)
        self.assertIn("Ankara'da gelişme", out)
        self.assertIn("Hürriyet", out)
        self.assertIn("TÜRKİYE", out)

    def test_text_prefers_direct_link(self):
        # Yayinci baglantisi varsa Google Haberler linki yerine o kullanilmali
        out = render_text(BULLETIN)
        self.assertIn("hurriyet.com.tr/haber-1", out)
        self.assertNotIn("news.google.com", out)

    def test_text_mentions_source_count(self):
        self.assertIn("5 yayıncı yazdı", render_text(BULLETIN))

    def test_html_escapes_content(self):
        risky = json.loads(json.dumps(BULLETIN))
        risky["segments"][0]["items"][0]["title"] = "<script>alert(1)</script>"
        out = render_html(risky)
        self.assertNotIn("<script>alert", out)
        self.assertIn("&lt;script&gt;", out)

    def test_html_needs_no_javascript(self):
        # NotebookLM ve tarayicisiz okuyucular JS calistirmaz
        self.assertNotIn("<script", render_html(BULLETIN))


class TestDocSync(unittest.TestCase):
    def test_missing_doc_id_raises(self):
        with self.assertRaises(DocSyncError):
            from mynews.gdocs import sync_document

            sync_document("metin", document_id="", credentials_json="{}")

    def test_invalid_credentials_json_raises(self):
        from mynews.gdocs import sync_document

        with self.assertRaises(DocSyncError):
            sync_document("metin", document_id="abc", credentials_json="{bozuk")

    def test_end_index_of_empty_document(self):
        # Bos belgede silinemeyen tek satir sonu vardir
        self.assertEqual(_document_end_index({"body": {"content": [{"endIndex": 2}]}}), 2)

    def test_end_index_takes_maximum(self):
        doc = {"body": {"content": [{"endIndex": 2}, {"endIndex": 480}, {"endIndex": 91}]}}
        self.assertEqual(_document_end_index(doc), 480)

    def test_service_account_email_extracted(self):
        raw = json.dumps({"client_email": "bot@proje.iam.gserviceaccount.com"})
        self.assertEqual(service_account_email(raw), "bot@proje.iam.gserviceaccount.com")

    def test_service_account_email_handles_garbage(self):
        self.assertEqual(service_account_email("bozuk"), "")


SUMMARY_BULLETIN = {
    "segments": [{
        "title": "Türkiye",
        "items": [
            {
                "title": "Manisa'da gizli kamera bulundu",
                "publisher": "Hürriyet",
                "summary": "Şehzadeler ilçesinde 21 şüpheli hakkında işlem başlatıldı.",
                "related": [{"source": "Cumhuriyet", "title": "Manisa'da skandal"}],
            },
            {
                "title": "Özeti olmayan haber",
                "publisher": "X",
                "summary": "",
                "related": [],
            },
        ],
    }],
}


class TestScriptContext(unittest.TestCase):
    def test_only_items_with_summary_included(self):
        # Baslikla yorum yapilmaz: ozeti olmayan haber senaryoya girmemeli
        context, raw = build_context(SUMMARY_BULLETIN)
        self.assertIn("Manisa", context)
        self.assertNotIn("Özeti olmayan haber", context)
        self.assertEqual(len(raw), 1)

    def test_context_carries_other_sources(self):
        context, _ = build_context(SUMMARY_BULLETIN)
        self.assertIn("Cumhuriyet", context)

    def test_max_items_respected(self):
        big = {"segments": [{"title": "T", "items": [
            {"title": f"Haber {i}", "publisher": "P", "summary": "Metin", "related": []}
            for i in range(20)
        ]}]}
        _, raw = build_context(big, max_items=5)
        self.assertEqual(len(raw), 5)


class TestScriptVerification(unittest.TestCase):
    def test_invented_number_dropped(self):
        # Kaynakta 21 var, 450 yok -> ikinci replik ayiklanmali
        sources = ["Şehzadeler ilçesinde 21 şüpheli hakkında işlem başlatıldı."]
        turns = [
            Turn("AYŞE", "Manisa'da 21 şüpheli hakkında işlem başlatılmış."),
            Turn("MERT", "Toplam 450 kişi gözaltına alındı."),
        ]
        kept, dropped = verify_turns(turns, sources)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 1)
        self.assertIn("450", dropped[0])

    def test_numberless_turns_kept(self):
        kept, dropped = verify_turns(
            [Turn("AYŞE", "Merhaba, bugünkü haberlere geçiyoruz.")], ["herhangi bir metin"]
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_single_digit_tolerated(self):
        # "2 haber", "3." gibi gunluk dil ayiklanmamali
        kept, _ = verify_turns([Turn("MERT", "Sırada 2 konu var.")], ["kaynak metni"])
        self.assertEqual(len(kept), 1)


class TestSummaryExtraction(unittest.TestCase):
    def test_prefers_longer_field(self):
        item = ET.fromstring(
            "<item><description>Kısa</description>"
            "<content:encoded xmlns:content='http://purl.org/rss/1.0/modules/content/'>"
            "Bu çok daha uzun bir gövde metnidir.</content:encoded></item>"
        )
        self.assertIn("gövde metnidir", extract_summary(item))

    def test_strips_html(self):
        item = ET.fromstring("<item><description>&lt;p&gt;Metin&lt;/p&gt;</description></item>")
        self.assertEqual(extract_summary(item), "Metin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
