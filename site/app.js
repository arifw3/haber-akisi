/* Haber Akışı — Google Haberler bülteni
 *
 * Dört ekran: Ana sayfa (öne çıkanlar + öneriler), Keşfet (arama + kategori),
 * Detay (olayın farklı kaynaklardaki halleri), Kayıtlı.
 *
 * Hands-free: sırayla seslendirir, mini oynatıcı her ekranda görünür.
 * Hazır ses dosyası varsa onu çalar; yoksa tarayıcının Türkçe sesine
 * (Web Speech API) düşer, böylece API anahtarı olmadan da çalışır.
 *
 * Görsel notu: Google Haberler RSS görsel vermiyor (media:content / enclosure /
 * thumbnail hiçbiri yok). Habere alakasız stok görsel koymak yanıltıcı olurdu;
 * onun yerine kategoriye göre deterministik gradient + yayıncı logosu kullanılıyor.
 */
"use strict";

const LANG_KEY = "mynews:lang";
const SUPPORTED = ["tr", "en"];

function initialLang() {
  const fromUrl = new URLSearchParams(location.search).get("lang");
  if (SUPPORTED.includes(fromUrl)) return fromUrl;
  const stored = localStorage.getItem(LANG_KEY);
  if (SUPPORTED.includes(stored)) return stored;
  // Tarayıcı dili destekleniyorsa onu kullan, yoksa Türkçe.
  const nav = (navigator.language || "tr").slice(0, 2);
  return SUPPORTED.includes(nav) ? nav : "tr";
}

const dataUrl = (lang) => `data/${lang}/latest.json`;
const SAVED_KEY = "mynews:saved";
const READ_KEY = "mynews:read";
const INTEREST_KEY = "mynews:interests";
const RATE_KEY = "mynews:rate";
const RATES = [1, 1.25, 1.5, 2];

/* Arayüz metinleri. Bülten içeriği sunucuda çevriliyor; buradakiler
 * yalnızca uygulamanın kendi etiketleri. */
const STRINGS = {
  tr: {
    featured: "Öne çıkanlar", more: "Öneriler", forYou: "Senin için", all: "Tümü",
    home: "Ana sayfa", discover: "Keşfet", listen: "Dinle", saved: "Kayıtlı",
    discoverSub: "Tüm kategorilerden haberler", savedSub: "Sonra okumak için ayırdıklarınız",
    search: "Haberlerde ara…", noMatch: "Eşleşen haber yok.", count: (n) => `${n} haber`,
    audioBriefing: "SESLİ BÜLTEN", dailyBriefing: "Günün bülteni",
    episodeMeta: (m) => `İki sunucu · ~${m} dakika`,
    podcastApp: "Podcast uygulamanda dinle", saveOffline: "Çevrimdışı dinlemek için kaydet",
    podcastMissing: "Bugünün sesli bülteni üretilemedi.",
    noSummary: "Bu haberin özeti alınamadı — yayıncının sayfasında okuyabilirsin.",
    a11yBack: "Geri", a11ySave: "Kaydet", a11yUnsave: "Kaydedilenlerden çıkar",
    a11yShare: "Paylaş", a11ySource: "Kaynağa git", a11ySearch: "Ara",
    a11yRefresh: "Yenile", a11yVerified: "doğrulanmış kaynak",
    audioMissing: "Bazı haberlerin seslendirmesi eksik.",
    bulletinIncomplete: "Bu bülten eksik derlendi.",
    downloading: (a, b) => `İndiriliyor… ${a}/${b}`, offlineReady: (n) => `Çevrimdışı hazır · ${n} ses`,
    offlineUnsupported: "Çevrimdışı kayıt bu tarayıcıda desteklenmiyor",
    interests: "İlgi alanların",
    interestsHelp: "Eşleşen haberler ana sayfada öne çıkar. Yalnızca bu cihazda saklanır.",
    interestsEmpty: "Henüz eklemedin.", interestPlaceholder: "örn. Laravel, deprem, Fenerbahçe",
    add: "Ekle", edit: "Düzenle", read: "okundu",
    sources: (n) => `${n} kaynak`, singleSource: "tek kaynak",
    listenHere: "Buradan dinle", otherSources: "Aynı olayı yazan diğer kaynaklar",
    sourceNote: "Özet yayıncının kendi akışından alındı; tam metin için kaynağa gidin.",
    sourceNoteBare: "Google Haberler makale gövdesi vermiyor; bu haber için elimizde yalnızca başlık var.",
    savedEmpty: "Henüz haber kaydetmediniz.", savedHint: "Bir haberi açıp yer imi düğmesine dokunun.",
    stale: (t) => `Bülten ${t} güncellenmedi. Bağlantını kontrol et ya da yenile.`,
    hours: (n) => `${n} saattir`, days: (n) => `${n} gündür`,
    speaking: (s) => `${s} konuşuyor`, loadFailed: "Bülten yüklenemedi.",
  },
  en: {
    featured: "Featured", more: "More stories", forYou: "For you", all: "All",
    home: "Home", discover: "Discover", listen: "Listen", saved: "Saved",
    discoverSub: "Stories from every category", savedSub: "Kept for later",
    search: "Search news…", noMatch: "No matching stories.", count: (n) => `${n} stories`,
    audioBriefing: "AUDIO BRIEFING", dailyBriefing: "Today's briefing",
    episodeMeta: (m) => `Two hosts · ~${m} min`,
    podcastApp: "Listen in your podcast app", saveOffline: "Save for offline listening",
    podcastMissing: "Today's audio briefing could not be produced.",
    noSummary: "No summary was available for this story — read it on the publisher's site.",
    a11yBack: "Back", a11ySave: "Save", a11yUnsave: "Remove from saved",
    a11yShare: "Share", a11ySource: "Go to source", a11ySearch: "Search",
    a11yRefresh: "Refresh", a11yVerified: "verified source",
    audioMissing: "Some stories are missing narration.",
    bulletinIncomplete: "This bulletin was compiled with gaps.",
    downloading: (a, b) => `Downloading… ${a}/${b}`, offlineReady: (n) => `Ready offline · ${n} clips`,
    offlineUnsupported: "Offline saving isn't supported in this browser",
    interests: "Your interests",
    interestsHelp: "Matching stories move to the top. Stored on this device only.",
    interestsEmpty: "Nothing added yet.", interestPlaceholder: "e.g. Laravel, climate, Arsenal",
    add: "Add", edit: "Edit", read: "read",
    sources: (n) => `${n} sources`, singleSource: "single source",
    listenHere: "Listen from here", otherSources: "Other outlets covering this",
    sourceNote: "The summary comes from the publisher's own feed; open the source for the full story.",
    sourceNoteBare: "Google News doesn't provide article bodies, so all we have for this story is the headline.",
    savedEmpty: "You haven't saved any stories yet.", savedHint: "Open a story and tap the bookmark.",
    stale: (t) => `The briefing hasn't updated for ${t}. Check your connection or refresh.`,
    hours: (n) => `${n} hours`, days: (n) => `${n} days`,
    speaking: (s) => `${s} speaking`, loadFailed: "Couldn't load the briefing.",
  },
};

function t(key, ...args) {
  const table = STRINGS[state.lang] || STRINGS.tr;
  const value = table[key] ?? STRINGS.tr[key] ?? key;
  return typeof value === "function" ? value(...args) : value;
}

const $ = (sel) => document.querySelector(sel);

const el = {
  topbar: $("#topbar"),
  view: $("#view"),
  player: $("#player"),
  mini: $("#mini"),
  miniTitle: $("#mini-title"),
  miniSub: $("#mini-sub"),
  miniToggle: $("#mini-toggle"),
  miniPlay: $("#mini-play"),
  miniPause: $("#mini-pause"),
  miniEq: $("#mini-eq"),
  miniNext: $("#mini-next"),
  miniRate: $("#mini-rate"),
  miniClose: $("#mini-close"),
};

const state = {
  bulletin: null,
  lang: initialLang(),
  view: "home",
  detailId: null,
  segment: "all",
  query: "",
  queue: [],
  index: 0,
  playing: false,
  rate: Number(localStorage.getItem(RATE_KEY)) || 1,
  voice: null,
  saved: new Set(JSON.parse(localStorage.getItem(SAVED_KEY) || "[]")),
  read: new Set(JSON.parse(localStorage.getItem(READ_KEY) || "[]")),
  interests: JSON.parse(localStorage.getItem(INTEREST_KEY) || "[]"),
  wakeLock: null,
};

/* Kategori paletleri — hero gradienti ve rozet rengi buradan türer. */
const PALETTE = {
  "turkiye":         { from: "#8f0f47", to: "#e0447f", chip: "bg-[#c2185b]" },
  "dunya":           { from: "#2d1b6b", to: "#6b4fc4", chip: "bg-[#4a35a0]" },
  "ekonomi":         { from: "#8a2a12", to: "#e0834f", chip: "bg-[#c25418]" },
  "bilim-teknoloji": { from: "#5c1478", to: "#b93bb0", chip: "bg-[#8e24aa]" },
  "bilim":           { from: "#0d4a38", to: "#2aa87f", chip: "bg-[#17795e]" },
  "saglik":          { from: "#0f4f5c", to: "#3aa8b0", chip: "bg-[#15788a]" },
  "spor":            { from: "#a81742", to: "#f4715c", chip: "bg-[#e0464f]" },
  "yazilim":         { from: "#26243f", to: "#6b5b9e", chip: "bg-[#464170]" },
};
const FALLBACK_PALETTE = { from: "#4a2338", to: "#8a5570", chip: "bg-[#7b5164]" };

/* ------------------------------------------------------------- yardımcılar */

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

/* Göreli zaman ve tarih, arayüz diline göre biçimlenir. */
const TIME_LABELS = {
  tr: { now: "az önce", hours: (n) => `${n} saat önce`, yesterday: "dün", days: (n) => `${n} gün önce` },
  en: { now: "just now", hours: (n) => `${n}h ago`, yesterday: "yesterday", days: (n) => `${n}d ago` },
};

function relativeTime(hours) {
  if (hours == null) return "";
  const l = TIME_LABELS[state.lang] || TIME_LABELS.tr;
  if (hours < 1) return l.now;
  if (hours < 24) return l.hours(Math.round(hours));
  const days = Math.round(hours / 24);
  return days === 1 ? l.yesterday : l.days(days);
}

function formatDate(iso) {
  try {
    const tag = state.lang === "en" ? "en-US" : "tr-TR";
    return new Date(iso).toLocaleDateString(tag, { day: "numeric", month: "long", year: "numeric" });
  } catch {
    return String(iso);
  }
}

function hashOf(text) {
  let h = 0;
  for (let i = 0; i < (text || "").length; i += 1) h = (h * 31 + text.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function paletteOf(item) {
  return PALETTE[item.segment] || FALLBACK_PALETTE;
}

function heroStyle(item) {
  const p = paletteOf(item);
  const angle = 118 + (hashOf(item.title) % 54);
  return `background-image:linear-gradient(${angle}deg, ${p.from}, ${p.to})`;
}

function persistSaved() {
  localStorage.setItem(SAVED_KEY, JSON.stringify([...state.saved]));
}

/* Okunan haberler: son 300 kayıt yeter, liste sınırsız büyümesin. */
function markRead(item) {
  if (!item || !item.link || state.read.has(item.link)) return;
  state.read.add(item.link);
  const trimmed = [...state.read].slice(-300);
  state.read = new Set(trimmed);
  localStorage.setItem(READ_KEY, JSON.stringify(trimmed));
}

function cycleRate() {
  const next = RATES[(RATES.indexOf(state.rate) + 1) % RATES.length];
  state.rate = next;
  localStorage.setItem(RATE_KEY, String(next));
  el.player.playbackRate = next;
  if (state.playing && !state.queue[state.index]?.audio) playCurrent();
  updateMini();
}

function allItems() {
  if (!state.bulletin) return [];
  return state.bulletin.segments.flatMap((seg) =>
    seg.items.map((item) => ({ ...item, segment: seg.key, segmentTitle: seg.title }))
  );
}

function itemById(id) {
  return allItems().find((i) => i.id === id) || null;
}

function filtered() {
  let items = state.segment === "all" ? interleaved() : allItems();
  if (state.segment !== "all") items = items.filter((i) => i.segment === state.segment);
  if (state.query) {
    const q = state.query.toLocaleLowerCase("tr");
    items = items.filter(
      (i) =>
        i.title.toLocaleLowerCase("tr").includes(q) ||
        (i.publisher || "").toLocaleLowerCase("tr").includes(q)
    );
  }
  return items;
}

/* Segmentleri sırayla harmanlar: düz skor sıralaması tek kategoriyi
 * kümeliyordu (tüm öne çıkanlar Spor, tüm öneriler Türkiye). */
function interleaved() {
  const buckets = new Map();
  for (const item of allItems()) {
    if (!buckets.has(item.segment)) buckets.set(item.segment, []);
    buckets.get(item.segment).push(item);
  }
  for (const list of buckets.values()) list.sort((a, b) => b.score - a.score);

  const out = [];
  let picked = true;
  while (picked) {
    picked = false;
    for (const list of buckets.values()) {
      const next = list.shift();
      if (next) {
        out.push(next);
        picked = true;
      }
    }
  }
  return out;
}

function savedItems() {
  return allItems().filter((i) => state.saved.has(i.link));
}

/* --------------------------------------------------------- ortak parçalar */

function logoMarkup(item, size = "h-7 w-7", textSize = "text-[11px]") {
  const initial = (item.publisher || "?").trim().charAt(0).toUpperCase();
  return `<span class="grid ${size} shrink-0 place-items-center overflow-hidden rounded-full bg-white ring-1 ring-black/5 ${textSize} font-bold text-ink-soft">
    <img src="${escapeHtml(item.favicon)}" alt="" loading="lazy" class="h-full w-full object-cover"
         onerror="this.replaceWith(document.createTextNode('${initial}'))">
  </span>`;
}

function verifiedBadge() {
  return `<svg class="h-[15px] w-[15px] shrink-0 text-brand-500" viewBox="0 0 24 24" fill="currentColor" role="img" aria-label="${escapeHtml(t("a11yVerified"))}">
    <path d="M12 2.2 14.3 4l2.9-.2.9 2.7 2.4 1.6-1 2.7 1 2.7-2.4 1.6-.9 2.7-2.9-.2L12 21.8 9.7 20l-2.9.2-.9-2.7L3.5 16l1-2.7-1-2.7 2.4-1.6.9-2.7 2.9.2z"/>
    <path d="m8.6 12.2 2.2 2.2 4.4-4.4" fill="none" stroke="#fff" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

function sourceBadge(count) {
  if (count < 3) {
    return `<span class="rounded-full bg-black/25 px-2 py-[3px] text-[11px] font-medium text-white/80 backdrop-blur">${escapeHtml(t("singleSource"))}</span>`;
  }
  return `<span class="inline-flex items-center gap-1 rounded-full bg-white/20 px-2 py-[3px] text-[11px] font-semibold text-white backdrop-blur">
    <svg class="h-3 w-3" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2 4 5.5v6c0 4.7 3.4 9 8 10.5 4.6-1.5 8-5.8 8-10.5v-6z"/></svg>${escapeHtml(t("sources", count))}
  </span>`;
}

function sourceChip(count) {
  const strong = count >= 3;
  return `<span class="inline-flex shrink-0 items-center gap-1 rounded-full ${strong ? "bg-brand-50 text-brand-700" : "bg-black/5 text-ink-faint"} px-2 py-[3px] text-[11px] font-semibold">
    ${strong ? `<svg class="h-3 w-3" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2 4 5.5v6c0 4.7 3.4 9 8 10.5 4.6-1.5 8-5.8 8-10.5v-6z"/></svg>${count} kaynak` : "tek kaynak"}
  </span>`;
}

/* Ana sayfadaki geniş kart */
/* Yayıncı feed'inden görsel eşleştiyse gradientin üstüne bindir.
 * Yüklenemezse img kendini siler, altındaki gradient görünür kalır. */
function imageLayer(item, extra = "") {
  if (!item.image) return "";
  return `<img src="${escapeHtml(item.image)}" alt="" loading="lazy"
      class="absolute inset-0 h-full w-full object-cover ${extra}"
      onerror="this.remove()">`;
}

/* Doğrudan yayıncı bağlantısı varsa onu kullan; yoksa Google Haberler linki. */
function targetUrl(item) {
  return item.source_url || item.link;
}

function heroCard(item) {
  const p = paletteOf(item);
  return `
  <article data-open="${escapeHtml(item.id)}" tabindex="0" role="link"
    aria-label="${escapeHtml(item.title)}"
    class="hero-tex relative focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 h-[15.5rem] w-[19.5rem] shrink-0 cursor-pointer snap-start overflow-hidden rounded-xl2 shadow-hero"
    style="${heroStyle(item)}">
    ${imageLayer(item)}
    ${item.image ? "" : `<span class="absolute right-5 top-3 text-[5.5rem] font-black leading-none text-white/[.07]">${escapeHtml((item.publisher || "?").charAt(0))}</span>`}
    <div class="absolute inset-x-0 bottom-0 h-3/4 bg-gradient-to-t from-black/80 via-black/35 to-transparent"></div>
    <span class="absolute left-4 top-4 rounded-full ${p.chip} px-3 py-1 text-[12px] font-semibold text-white shadow">${escapeHtml(item.segmentTitle)}</span>
    <div class="absolute inset-x-0 bottom-0 p-4">
      <div class="flex items-center gap-1.5 text-[12.5px] text-white/85">
        <span class="truncate font-medium">${escapeHtml(item.publisher)}</span>
        ${verifiedBadge()}
        <span class="text-white/60">•</span>
        <span class="shrink-0">${relativeTime(item.age_hours)}</span>
      </div>
      <h3 class="mt-1.5 line-clamp-2 text-[18px] font-bold leading-snug text-white">${escapeHtml(item.title)}</h3>
      <div class="mt-2">${sourceBadge(item.source_count)}</div>
    </div>
  </article>`;
}

/* Liste satırı */
function listRow(item) {
  return `
  <article data-open="${escapeHtml(item.id)}" tabindex="0" role="link"
    aria-label="${escapeHtml(item.title)}"
    class="flex cursor-pointer gap-3 rounded-2xl py-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-600${
    state.read.has(item.link) ? " opacity-55" : ""
  }">
    <div class="hero-tex relative h-[4.6rem] w-[4.6rem] shrink-0 overflow-hidden rounded-2xl" style="${heroStyle(item)}">
      ${item.image
        ? imageLayer(item)
        : `<span class="absolute inset-0 grid place-items-center text-[26px] font-black text-white/25">${escapeHtml((item.publisher || "?").charAt(0))}</span>`}
    </div>
    <div class="min-w-0 flex-1">
      <p class="flex items-center gap-1.5 text-[12.5px] font-medium text-ink-faint">
        ${escapeHtml(item.segmentTitle)}
        ${matchedInterests(item).slice(0, 1).map((w) => `<span class="rounded-full bg-brand-100 px-1.5 py-px text-[11px] font-semibold text-brand-700">${escapeHtml(w)}</span>`).join("")}
      </p>
      <h3 class="mt-0.5 line-clamp-2 text-[15.5px] font-semibold leading-snug">${escapeHtml(item.title)}</h3>
      ${state.read.has(item.link) ? '<span class="mt-1 inline-block text-[11px] font-medium text-ink-faint">${escapeHtml(t("read"))}</span>' : ""}
      <div class="mt-1.5 flex items-center gap-2">
        ${logoMarkup(item, "h-5 w-5", "text-[10px]")}
        <span class="truncate text-[12.5px] text-ink-soft">${escapeHtml(item.publisher)}</span>
        <span class="text-ink-faint">•</span>
        <span class="shrink-0 text-[12.5px] text-ink-faint">${relativeTime(item.age_hours)}</span>
      </div>
    </div>
  </article>`;
}

function sectionHeader(title, action) {
  return `<div class="flex items-baseline justify-between">
    <h2 class="text-[19px] font-bold tracking-tight">${escapeHtml(title)}</h2>
    ${action ? `<button data-nav-to="${action.view}" class="text-[13.5px] font-semibold text-brand-600">${escapeHtml(action.label)}</button>` : ""}
  </div>`;
}

/* ------------------------------------------------------------- üst çubuk */

function renderTopbar() {
  if (state.view === "detail") {
    el.topbar.innerHTML = "";
    el.topbar.classList.add("hidden");
    return;
  }
  el.topbar.classList.remove("hidden");

  if (state.view === "home") {
    el.topbar.innerHTML = `
      <div class="flex items-center justify-between">
        <div class="min-w-0">
          <p class="text-[12.5px] font-medium text-ink-faint">${escapeHtml(formatDate(state.bulletin?.generated_at))}</p>
          <h1 class="text-[24px] font-bold leading-tight tracking-tight">${escapeHtml(state.bulletin?.title || "Haber Akışı")}</h1>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <button data-lang class="h-11 rounded-full bg-white px-3 text-[13px] font-bold uppercase shadow-card transition active:scale-95"
            aria-label="Language">${escapeHtml(state.lang)}</button>
          <button data-nav-to="discover" class="grid h-11 w-11 place-items-center rounded-full bg-white shadow-card transition active:scale-95" aria-label="${escapeHtml(t("a11ySearch"))}">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2" stroke-linecap="round"/></svg>
          </button>
          <button id="btn-refresh" class="relative grid h-11 w-11 place-items-center rounded-full bg-white shadow-card transition active:scale-95" aria-label="${escapeHtml(t("a11yRefresh"))}">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path d="M20 11a8 8 0 1 0-2.3 5.7" stroke-linecap="round"/><path d="M20 4v7h-7" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
      </div>`;
    return;
  }

  const titles = {
    discover: [t("discover"), t("discoverSub")],
    saved: [t("saved"), t("savedSub")],
  };
  const [title, sub] = titles[state.view] || ["", ""];
  el.topbar.innerHTML = `
    <button data-nav-to="home" class="mb-2 grid h-11 w-11 place-items-center rounded-full bg-white shadow-card transition active:scale-95" aria-label="${escapeHtml(t("a11yBack"))}">
      <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="m14 6-6 6 6 6" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <h1 class="text-[30px] font-bold leading-tight tracking-tight">${escapeHtml(title)}</h1>
    <p class="mt-0.5 text-[13.5px] text-ink-soft">${escapeHtml(sub)}</p>`;
}

/* ---------------------------------------------------------------- ekranlar */

/* Podcast replikleri oynatıcının beklediği biçime çevrilir: aynı kuyruk
 * mantığı hem haber bülteni hem podcast için kullanılıyor. */
function podcastQueue() {
  const episode = state.bulletin && state.bulletin.podcast;
  if (!episode || !episode.turns || !episode.turns.length) return [];
  return episode.turns.map((turn, i) => ({
    id: `podcast-${i}`,
    title: turn.text,
    publisher: turn.speaker,
    speech: turn.text,
    audio: turn.audio,
    segment: "podcast",
    segmentTitle: "Günün bülteni",
    source_count: 0,
    related: [],
    link: "",
  }));
}

/* Bültendeki tüm sesleri (haberler + podcast) service worker'a indirtir.
 * Sabah wifi'dayken kaydet, yolda çevrimdışı dinle. */
function audioUrls() {
  const urls = new Set();
  allItems().forEach((i) => i.audio && urls.add(i.audio));
  const episode = state.bulletin && state.bulletin.podcast;
  (episode?.turns || []).forEach((t) => t.audio && urls.add(t.audio));
  return [...urls];
}

function saveOffline(button) {
  const urls = audioUrls();
  if (!urls.length || !navigator.serviceWorker?.controller) {
    if (button) button.textContent = t("offlineUnsupported");
    return;
  }
  state.offlineTotal = urls.length;
  if (button) button.textContent = t("downloading", 0, urls.length);
  navigator.serviceWorker.controller.postMessage({ type: "cache-audio", urls });
}

navigator.serviceWorker?.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type !== "cache-audio-progress") return;
  const button = $("#offline-btn");
  if (!button) return;
  button.textContent =
    data.done + data.failed >= data.total
      ? t("offlineReady", data.done)
      : t("downloading", data.done, data.total);
});

/* Veri bayatladıysa görünür uyarı: sessiz bozulmayı kullanıcı da fark etsin. */
function freshnessNotice() {
  const generated = state.bulletin && state.bulletin.generated_at;
  if (!generated) return "";
  const hours = (Date.now() - new Date(generated).getTime()) / 36e5;
  if (hours < 36) return "";
  const gun = Math.round(hours / 24);
  return `<p class="mb-4 rounded-2xl bg-amber-100 px-4 py-3 text-[13px] font-medium text-amber-900">
    ${escapeHtml(t("stale", gun < 1 ? t("hours", Math.round(hours)) : t("days", gun)))}
  </p>`;
}

/* Bültenin kendi eksiğini söylemesi. Denetim şimdiye kadar yalnızca
 * GitHub Actions sekmesinde duruyordu; oraya kimse bakmadığı için beş gün
 * üst üste kırmızı yandı ve fark edilmedi. Okuyucunun umursayacağı iki
 * eksik (podcast ve seslendirme) burada adıyla söyleniyor; geri kalanı
 * bakım tarafını ilgilendirdiği için tek bir genel satıra iniyor. */
const CHECK_LABELS = {
  "podcast bolumu": "podcastMissing",
  seslendirme: "audioMissing",
};

function checkNotice() {
  const check = state.bulletin && state.bulletin.check;
  if (!check || check.ok) return "";
  const failed = check.failed || [];
  if (!failed.length) return "";

  const known = failed.map((f) => CHECK_LABELS[f.name]).filter(Boolean);
  const mesaj = known.length ? known.map((k) => t(k)).join(" · ") : t("bulletinIncomplete");

  return `<p class="mb-4 rounded-2xl bg-black/5 px-4 py-3 text-[13px] text-ink-soft">
    ${escapeHtml(mesaj)}
  </p>`;
}

/* İlgi alanları: kullanıcının yazdığı anahtar kelimeler tarayıcıda saklanır.
 * Eşleşen haberler ana sayfada "Senin için" bölümünde öne çıkar. Sunucu
 * tarafını değiştirmez — herkes kendi listesini tutar. */
function persistInterests() {
  localStorage.setItem(INTEREST_KEY, JSON.stringify(state.interests));
}

function matchedInterests(item) {
  if (!state.interests.length) return [];
  const haystack = [item.title, item.summary, item.publisher, item.segmentTitle]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase("tr");
  return state.interests.filter((word) => haystack.includes(word.toLocaleLowerCase("tr")));
}

function interestItems() {
  if (!state.interests.length) return [];
  return allItems()
    .filter((i) => matchedInterests(i).length)
    .sort((a, b) => b.score - a.score);
}

function interestEditor() {
  const chips = state.interests
    .map(
      (word) => `<button data-remove-interest="${escapeHtml(word)}"
        class="inline-flex items-center gap-1 rounded-full bg-brand-100 px-3 py-1.5 text-[13px] font-semibold text-brand-700">
        ${escapeHtml(word)}
        <svg class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18" stroke-linecap="round"/></svg>
      </button>`
    )
    .join("");

  return `
  <section class="mb-5 rounded-xl2 bg-white p-4 shadow-card">
    <h2 class="text-[15px] font-bold">${escapeHtml(t("interests"))}</h2>
    <p class="mt-0.5 text-[12.5px] text-ink-soft">${escapeHtml(t("interestsHelp"))}</p>
    <div class="mt-3 flex flex-wrap gap-2">${chips || `<span class="text-[13px] text-ink-faint">${escapeHtml(t("interestsEmpty"))}</span>`}</div>
    <form data-interest-form class="mt-3 flex gap-2">
      <input name="word" type="text" placeholder="${escapeHtml(t("interestPlaceholder"))}" autocomplete="off"
        class="min-w-0 flex-1 rounded-xl border-0 bg-black/[.04] px-3 py-2.5 text-[14px] outline-none placeholder:text-ink-faint focus:ring-2 focus:ring-brand-500">
      <button type="submit" class="grad shrink-0 rounded-xl px-4 py-2.5 text-[14px] font-semibold text-white">${escapeHtml(t("add"))}</button>
    </form>
  </section>`;
}

function podcastCard() {
  const turns = podcastQueue();
  if (!turns.length) return "";
  const dakika = Math.max(1, Math.round(turns.reduce((n, t) => n + t.title.split(" ").length, 0) / 150));
  return `
  <button data-podcast class="hero-tex relative mb-3 w-full overflow-hidden rounded-xl2 p-5 text-left shadow-hero"
    style="background-image:linear-gradient(115deg,#6d1440,#d81b60 60%,#f4728c)">
    <div class="relative flex items-center gap-4">
      <span class="grid h-14 w-14 shrink-0 place-items-center rounded-full bg-white/20 backdrop-blur">
        <svg class="h-6 w-6 translate-x-[1px] text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5.5v13l11-6.5z"/></svg>
      </span>
      <span class="min-w-0 flex-1">
        <span class="block text-[12px] font-semibold uppercase tracking-wide text-white/70">${escapeHtml(t("audioBriefing"))}</span>
        <span class="block text-[17px] font-bold leading-tight text-white">${escapeHtml(t("dailyBriefing"))}</span>
        <span class="block text-[13px] text-white/75">${escapeHtml(t("episodeMeta", dakika))}</span>
      </span>
    </div>
  </button>
  <a href="podcast-${state.lang}.xml" target="_blank" rel="noopener"
     class="mb-5 -mt-3 flex items-center justify-center gap-1.5 text-[12.5px] font-medium text-ink-soft">
    <svg class="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6.2 17.8a1.5 1.5 0 1 1-2.1 2.1 1.5 1.5 0 0 1 2.1-2.1zM4 11.5a8.5 8.5 0 0 1 8.5 8.5h-2.6A5.9 5.9 0 0 0 4 14.1zM4 5a15 15 0 0 1 15 15h-2.6A12.4 12.4 0 0 0 4 7.6z"/>
    </svg>
    ${escapeHtml(t("podcastApp"))}
  </a>
  <button id="offline-btn" data-offline
    class="mb-5 -mt-3 flex w-full items-center justify-center gap-1.5 text-[12.5px] font-medium text-ink-soft">
    <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
      <path d="M12 4v11m0 0 4-4m-4 4-4-4" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M5 19h14" stroke-linecap="round"/>
    </svg>
    ${escapeHtml(t("saveOffline"))}
  </button>`;
}

function renderHome() {
  const ordered = interleaved();
  const featured = ordered.slice(0, 6);
  const mine = interestItems().slice(0, 6);
  const mineIds = new Set(mine.map((i) => i.id));
  const rest = ordered.slice(6, 21).filter((i) => !mineIds.has(i.id));

  el.view.innerHTML = `
    <div class="view">
      ${freshnessNotice()}
      ${checkNotice()}
      ${podcastCard()}
      ${sectionHeader(t("featured"), { label: t("all"), view: "discover" })}
      <div id="carousel" class="no-scrollbar snap-x-mandatory -mx-5 mt-3 flex gap-3 overflow-x-auto px-5 pb-2">
        ${featured.map(heroCard).join("")}
      </div>
      <div id="dots" class="mt-1 flex justify-center gap-1.5">
        ${featured.map((_, i) => `<span class="h-1.5 rounded-full transition-all ${i === 0 ? "w-5 bg-[#d81b60]" : "w-1.5 bg-ink-faint/40"}"></span>`).join("")}
      </div>

      ${
        mine.length
          ? `<div class="mt-6">
               ${sectionHeader(t("forYou"), { label: t("edit"), view: "discover" })}
               <div class="mt-1 divide-y divide-black/5">${mine.map(listRow).join("")}</div>
             </div>`
          : ""
      }

      <div class="mt-6">
        ${sectionHeader(t("more"), { label: t("all"), view: "discover" })}
        <div class="mt-1 divide-y divide-black/5">${rest.map(listRow).join("")}</div>
      </div>
    </div>`;

  wireCarousel();
}

function wireCarousel() {
  const carousel = $("#carousel");
  const dots = $("#dots");
  if (!carousel || !dots) return;
  carousel.addEventListener(
    "scroll",
    () => {
      const card = carousel.firstElementChild;
      if (!card) return;
      const width = card.getBoundingClientRect().width + 12;
      const active = Math.round(carousel.scrollLeft / width);
      [...dots.children].forEach((dot, i) => {
        dot.className = `h-1.5 rounded-full transition-all ${i === active ? "w-5 bg-[#d81b60]" : "w-1.5 bg-ink-faint/40"}`;
      });
    },
    { passive: true }
  );
}

function discoverList(items) {
  return items.length
    ? items.map(listRow).join("")
    : `<p class="py-16 text-center text-[15px] text-ink-soft">${escapeHtml(t("noMatch"))}</p>`;
}

function renderDiscover() {
  const segments = state.bulletin ? state.bulletin.segments : [];
  const chips = [{ key: "all", title: t("all") }, ...segments.map((s) => ({ key: s.key, title: s.title }))];
  const items = filtered();

  el.view.innerHTML = `
    <div class="view">
      ${interestEditor()}
      <div class="relative mt-1">
        <svg class="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2" stroke-linecap="round"/>
        </svg>
        <input id="search" type="search" value="${escapeHtml(state.query)}" placeholder="${escapeHtml(t("search"))}" autocomplete="off"
          class="w-full rounded-2xl border-0 bg-white py-3.5 pl-12 pr-4 text-[15px] shadow-card outline-none ring-1 ring-black/5 placeholder:text-ink-faint focus:ring-2 focus:ring-brand-500">
      </div>

      <div class="no-scrollbar -mx-5 mt-4 flex gap-2 overflow-x-auto px-5">
        ${chips
          .map((c) => {
            const active = c.key === state.segment;
            return `<button data-chip="${c.key}" class="shrink-0 rounded-full px-4 py-2 text-[14px] font-semibold transition active:scale-95 ${
              active ? "grad text-white shadow-pill" : "bg-white text-ink-soft ring-1 ring-black/5"
            }">${escapeHtml(c.title)}</button>`;
          })
          .join("")}
      </div>

      <p id="count" class="mt-4 text-[13px] text-ink-faint">${escapeHtml(t("count", items.length))}</p>
      <div id="results" class="divide-y divide-black/5">${discoverList(items)}</div>
    </div>`;

  $("#search")?.addEventListener("input", (event) => {
    state.query = event.target.value.trim();
    const list = filtered();
    $("#count").textContent = t("count", list.length);
    $("#results").innerHTML = discoverList(list);
  });
}

function renderSaved() {
  const items = savedItems();
  el.view.innerHTML = `
    <div class="view mt-2">
      ${
        items.length
          ? `<div class="divide-y divide-black/5">${items.map(listRow).join("")}</div>`
          : `<div class="grid place-items-center py-24 text-center">
               <svg class="h-12 w-12 text-ink-faint/50" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                 <path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z" stroke-linejoin="round"/>
               </svg>
               <p class="mt-3 text-[15px] text-ink-soft">${escapeHtml(t("savedEmpty"))}</p>
               <p class="mt-1 text-[13.5px] text-ink-faint">${escapeHtml(t("savedHint"))}</p>
             </div>`
      }
    </div>`;
}

/* Detay sayfasının gövde metni.
 *
 * Burada uzun süre item.speech gösterildi ve bu yanlıştı: speech, metni
 * okunabilir kılmak için değil SESLENDİRİLEBİLİR kılmak için üretiliyor.
 * Yayıncı adı telaffuza açılıyor (BloombergHT -> "Bloomberg Ha Te"),
 * başlık gövdenin başında tekrar ediyor, noktalama düzleşiyor ve sonuna
 * "Bu haberi 5 ayrı kaynak yazdı." gibi konuşma cümleleri ekleniyor.
 * Okuyucu, başlığın hemen altında başlığın bozulmuş halini görüyordu.
 *
 * Doğrusu yayıncının kendi özeti. Özet yoksa uydurma yapılmıyor: haberin
 * yalnızca başlığı elimizde olduğu dürüstçe söyleniyor. */
function bodyText(item) {
  if (item.summary) {
    return `<p class="mt-5 text-[16px] leading-relaxed text-ink-soft">${escapeHtml(item.summary)}</p>`;
  }
  return `<p class="mt-5 text-[14.5px] leading-relaxed text-ink-faint">${escapeHtml(t("noSummary"))}</p>`;
}

function renderDetail() {
  const item = itemById(state.detailId);
  if (!item) return navigate("home");
  markRead(item);

  const p = paletteOf(item);
  const saved = state.saved.has(item.link);
  const related = (item.related || []).filter((r) => r.title && r.title !== item.title);

  el.view.innerHTML = `
    <div class="view -mx-5">
      <section class="hero-tex relative h-[19rem]" style="${heroStyle(item)}">
        ${imageLayer(item)}
        ${item.image ? "" : `<span class="absolute right-6 top-6 text-[9rem] font-black leading-none text-white/[.07]">${escapeHtml((item.publisher || "?").charAt(0))}</span>`}
        <div class="absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-black/85 via-black/40 to-transparent"></div>

        <div class="absolute inset-x-0 top-0 flex items-center justify-between px-5 pt-[max(1rem,env(safe-area-inset-top))]">
          <button data-back class="grid h-11 w-11 place-items-center rounded-full bg-black/30 text-white backdrop-blur transition active:scale-95" aria-label="${escapeHtml(t("a11yBack"))}">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="m14 6-6 6 6 6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <div class="flex gap-2">
            <button data-save class="grid h-11 w-11 place-items-center rounded-full ${saved ? "grad" : "bg-black/30"} text-white backdrop-blur transition active:scale-95" aria-label="${escapeHtml(saved ? t("a11yUnsave") : t("a11ySave"))}">
              <svg class="h-5 w-5" fill="${saved ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.9" viewBox="0 0 24 24">
                <path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z" stroke-linejoin="round"/>
              </svg>
            </button>
            <button data-share class="grid h-11 w-11 place-items-center rounded-full bg-black/30 text-white backdrop-blur transition active:scale-95" aria-label="${escapeHtml(t("a11yShare"))}">
              <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.9" viewBox="0 0 24 24">
                <circle cx="18" cy="5.5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="18.5" r="2.5"/>
                <path d="m8.2 10.8 7.6-4M8.2 13.2l7.6 4" stroke-linecap="round"/>
              </svg>
            </button>
          </div>
        </div>

        <div class="absolute inset-x-0 bottom-0 p-5 pb-9">
          <span class="rounded-full ${p.chip} px-3 py-1 text-[12px] font-semibold text-white shadow">${escapeHtml(item.segmentTitle)}</span>
          <h1 class="mt-3 text-[25px] font-bold leading-[1.22] text-white">${escapeHtml(item.title)}</h1>
          <p class="mt-2 text-[13px] text-white/75">${relativeTime(item.age_hours)} · ${escapeHtml(item.domain)}</p>
        </div>
      </section>

      <section class="relative -mt-8 min-h-[60vh] rounded-t-xl3 bg-white px-5 pb-10 pt-6 shadow-[0_-12px_30px_-18px_rgba(13,18,32,.35)]">
        <div class="flex items-center gap-2.5">
          ${logoMarkup(item, "h-11 w-11", "text-[16px]")}
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5">
              <p class="truncate text-[16px] font-bold">${escapeHtml(item.publisher)}</p>
              ${verifiedBadge()}
            </div>
            <p class="truncate text-[12.5px] text-ink-faint">${escapeHtml(item.domain)}</p>
          </div>
          ${sourceChip(item.source_count)}
        </div>

        ${bodyText(item)}

        ${
          related.length
            ? `<h2 class="mt-7 text-[15px] font-bold">${escapeHtml(t("otherSources"))}</h2>
               <ul class="mt-3 space-y-3">
                 ${related
                   .map(
                     (r) => `<li class="flex gap-2.5">
                       <span class="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full" style="background:${p.to}"></span>
                       <span class="min-w-0 text-[14.5px] leading-snug text-ink-soft">
                         <span class="font-semibold text-ink">${escapeHtml(r.source)}</span> — ${escapeHtml(r.title)}
                       </span>
                     </li>`
                   )
                   .join("")}
               </ul>`
            : ""
        }

        <div class="mt-7 flex items-center gap-2">
          <button data-listen class="grad inline-flex flex-1 items-center justify-center gap-2 rounded-full px-5 py-3.5 text-[15px] font-semibold text-white shadow-pill transition active:scale-[.98]">
            <svg class="h-[18px] w-[18px]" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5.5v13l11-6.5z"/></svg>
            ${escapeHtml(t("listenHere"))}
          </button>
          <a href="${escapeHtml(targetUrl(item))}" target="_blank" rel="noopener noreferrer"
             class="grid h-[3.15rem] w-[3.15rem] shrink-0 place-items-center rounded-full bg-black/5 text-ink-soft transition active:scale-95" aria-label="${escapeHtml(t("a11ySource"))}">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.9" viewBox="0 0 24 24">
              <path d="M14 5h5v5M19 5l-8.5 8.5" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M18 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4" stroke-linecap="round"/>
            </svg>
          </a>
        </div>

        <p class="mt-4 text-[12px] leading-relaxed text-ink-faint">
          ${escapeHtml(item.summary ? t("sourceNote") : t("sourceNoteBare"))}
        </p>
      </section>
    </div>`;
}

const RENDERERS = { home: renderHome, discover: renderDiscover, saved: renderSaved, detail: renderDetail };

function navigate(view, param) {
  state.view = view;
  if (view === "detail") state.detailId = param;

  renderTopbar();
  (RENDERERS[view] || renderHome)();
  setNav(view);
  window.scrollTo(0, 0);
}

function setNav(view) {
  const active = view === "detail" ? null : view;
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    const on = btn.dataset.nav === active;
    btn.classList.toggle("grad", on);
    btn.classList.toggle("text-white", on);
    btn.classList.toggle("shadow-pill", on);
    btn.classList.toggle("text-ink-faint", !on);
    const label = btn.querySelector(".nav-label");
    label.textContent = t(btn.dataset.nav);
    label.classList.toggle("hidden", !on);
  });
}

/* ------------------------------------------------------------ hands-free */

function pickVoice() {
  const voices = speechSynthesis.getVoices();
  const prefix = state.lang === "en" ? "en" : "tr";
  const exact = state.lang === "en" ? "en-US" : "tr-TR";
  return (
    voices.find((v) => v.lang === exact) ||
    voices.find((v) => (v.lang || "").toLowerCase().startsWith(prefix)) ||
    null
  );
}

function initVoices() {
  if (!("speechSynthesis" in window)) return;
  state.voice = pickVoice();
  if (!state.voice) {
    speechSynthesis.onvoiceschanged = () => {
      state.voice = pickVoice();
    };
  }
}

// Chrome uzun konuşmalarda ~15 sn sonra sessizce durur; canlı tutar.
let keepAlive = null;
function startKeepAlive() {
  stopKeepAlive();
  keepAlive = setInterval(() => {
    if (speechSynthesis.speaking && !speechSynthesis.paused) {
      speechSynthesis.pause();
      speechSynthesis.resume();
    }
  }, 9000);
}
function stopKeepAlive() {
  if (keepAlive) clearInterval(keepAlive);
  keepAlive = null;
}

function advance() {
  if (!state.playing) return;
  if (state.index >= state.queue.length - 1) return stopListening(true);
  state.index += 1;
  playCurrent();
}

function playCurrent() {
  const item = state.queue[state.index];
  if (!item) return stopListening();

  if ("speechSynthesis" in window) speechSynthesis.cancel();
  el.player.pause();
  updateMini();

  // Detay ekranındaysak dinlenen haber kendiliğinden öne gelsin.
  if (state.view === "detail" && item.segment !== "podcast" && state.detailId !== item.id) {
    state.detailId = item.id;
    renderDetail();
  }

  if (item.segment !== "podcast") markRead(item);

  if (item.audio) {
    el.player.src = item.audio;
    el.player.playbackRate = state.rate;
    el.player.onended = advance;
    el.player.play().catch(() => speakItem(item));
    return;
  }
  speakItem(item);
}

function speakItem(item) {
  if (!("speechSynthesis" in window)) {
    el.miniSub.textContent = "Tarayıcı seslendirmeyi desteklemiyor";
    state.playing = false;
    return;
  }
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(item.speech || item.title);
  utter.lang = state.lang === "en" ? "en-US" : "tr-TR";
  utter.rate = state.rate;
  if (state.voice) utter.voice = state.voice;
  utter.onend = advance;
  utter.onerror = (event) => {
    if (event.error && !["interrupted", "canceled"].includes(event.error)) stopListening();
  };
  speechSynthesis.speak(utter);
  startKeepAlive();
}

async function requestWakeLock() {
  try {
    if ("wakeLock" in navigator) state.wakeLock = await navigator.wakeLock.request("screen");
  } catch {
    /* pil tasarrufu modunda reddedilebilir */
  }
}

function releaseWakeLock() {
  if (state.wakeLock) {
    state.wakeLock.release().catch(() => {});
    state.wakeLock = null;
  }
}

function startListening(queue, startIndex = 0) {
  if (!queue.length) return;
  state.queue = queue;
  state.index = Math.max(0, startIndex);
  state.playing = true;
  requestWakeLock();
  playCurrent();
}

function stopListening(finished = false) {
  state.playing = false;
  stopKeepAlive();
  releaseWakeLock();
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  el.player.onended = null;
  el.player.pause();
  if (finished) state.index = 0;
  updateMini();
}

function pauseListening() {
  state.playing = false;
  stopKeepAlive();
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  el.player.pause();
  updateMini();
}

function updateMini() {
  const item = state.queue[state.index];
  el.mini.classList.toggle("hidden", !item);
  if (!item) return;

  el.miniTitle.textContent = item.title;
  const etiket = item.segment === "podcast" ? t("speaking", item.publisher) : item.publisher;
  el.miniSub.textContent = `${etiket} · ${state.index + 1}/${state.queue.length}`;
  el.miniPlay.classList.toggle("hidden", state.playing);
  el.miniPause.classList.toggle("hidden", !state.playing);
  el.miniEq.style.visibility = state.playing ? "visible" : "hidden";
  if (el.miniRate) el.miniRate.textContent = `${state.rate}×`;
  el.miniToggle.setAttribute("aria-label", state.playing ? "Duraklat" : "Devam et");
}

/* ---------------------------------------------------------- etkileşimler */

document.addEventListener("click", (event) => {
  const nav = event.target.closest("[data-nav]");
  if (nav) {
    const view = nav.dataset.nav;
    if (view === "listen") {
      if (state.playing) return pauseListening();
      if (state.queue.length) {
        state.playing = true;
        requestWakeLock();
        return playCurrent();
      }
      const queue = filtered().length ? filtered() : allItems();
      return startListening(queue);
    }
    return navigate(view);
  }

  const navTo = event.target.closest("[data-nav-to]");
  if (navTo) return navigate(navTo.dataset.navTo);

  const open = event.target.closest("[data-open]");
  if (open) return navigate("detail", open.dataset.open);

  const chip = event.target.closest("[data-chip]");
  if (chip) {
    state.segment = chip.dataset.chip;
    return renderDiscover();
  }

  if (event.target.closest("[data-back]")) return navigate("home");

  if (event.target.closest("[data-save]")) {
    const item = itemById(state.detailId);
    if (!item) return;
    if (state.saved.has(item.link)) state.saved.delete(item.link);
    else state.saved.add(item.link);
    persistSaved();
    return renderDetail();
  }

  if (event.target.closest("[data-share]")) {
    const item = itemById(state.detailId);
    if (!item) return;
    if (navigator.share) navigator.share({ title: item.title, url: targetUrl(item) }).catch(() => {});
    else navigator.clipboard?.writeText(targetUrl(item)).catch(() => {});
    return;
  }

  if (event.target.closest("[data-listen]")) {
    const item = itemById(state.detailId);
    if (!item) return;
    const queue = allItems();
    return startListening(queue, queue.findIndex((i) => i.id === item.id));
  }

  if (event.target.closest("[data-lang]")) return switchLang();

  const removeInterest = event.target.closest("[data-remove-interest]");
  if (removeInterest) {
    state.interests = state.interests.filter((w) => w !== removeInterest.dataset.removeInterest);
    persistInterests();
    return renderDiscover();
  }

  const offline = event.target.closest("[data-offline]");
  if (offline) return saveOffline(offline);

  if (event.target.closest("[data-podcast]")) {
    const queue = podcastQueue();
    if (queue.length) return startListening(queue);
    return;
  }

  if (event.target.closest("#btn-refresh")) return refresh();
});

el.miniToggle.addEventListener("click", () => {
  if (state.playing) return pauseListening();
  state.playing = true;
  requestWakeLock();
  playCurrent();
});

el.miniRate?.addEventListener("click", cycleRate);

el.miniNext.addEventListener("click", () => {
  if (state.index >= state.queue.length - 1) return;
  state.index += 1;
  if (state.playing) playCurrent();
  else updateMini();
});

el.miniClose.addEventListener("click", () => {
  stopListening(true);
  state.queue = [];
  updateMini();
});

document.addEventListener("submit", (event) => {
  const form = event.target.closest("[data-interest-form]");
  if (!form) return;
  event.preventDefault();
  const word = form.word.value.trim();
  if (word && !state.interests.includes(word)) {
    state.interests.push(word);
    persistInterests();
  }
  form.reset();
  renderDiscover();
});

document.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT") return;
  if (event.key === "Escape" && state.view === "detail") return navigate("home");

  // Klavyeyle gezinme: odaktaki kart Enter veya boşlukla açılır.
  if (event.key === "Enter" || event.key === " ") {
    const card = event.target.closest?.("[data-open]");
    if (card) {
      event.preventDefault();
      navigate("detail", card.dataset.open);
    }
  }
});

// Sekme arka plana alınınca konuşma bozulur; hazır ses dosyası çalmaya devam edebilir.
document.addEventListener("visibilitychange", () => {
  const item = state.queue[state.index];
  if (document.hidden && state.playing && !(item && item.audio)) pauseListening();
});

/* ------------------------------------------------------------- başlangıç */

async function loadBulletin() {
  const res = await fetch(dataUrl(state.lang), { cache: "no-cache" });
  if (!res.ok) throw new Error(`Bülten yüklenemedi (${res.status})`);
  return res.json();
}

function showError(message) {
  el.view.innerHTML = `<p class="py-20 text-center text-[15px] text-ink-soft">${escapeHtml(message)}</p>`;
}

/* Dil değiştir: bülten yeniden yüklenir, tercih hatırlanır. */
async function switchLang() {
  const next = SUPPORTED[(SUPPORTED.indexOf(state.lang) + 1) % SUPPORTED.length];
  state.lang = next;
  localStorage.setItem(LANG_KEY, next);
  document.documentElement.lang = next;
  stopListening(true);
  state.queue = [];
  await refresh();
}

async function refresh() {
  try {
    state.bulletin = await loadBulletin();
    navigate("home");
  } catch (err) {
    showError(err.message);
  }
}

async function init() {
  document.documentElement.lang = state.lang;
  initVoices();
  try {
    state.bulletin = await loadBulletin();
  } catch (err) {
    showError(t("loadFailed") + " " + err.message);
    return;
  }

  // Derin bağlantı: ?v=discover|saved, ?id=<haber>, ?autoplay=1
  const params = new URLSearchParams(location.search);
  const wanted = params.get("v");
  const wantedId = params.get("id");

  if (wantedId && itemById(wantedId)) navigate("detail", wantedId);
  else if (wanted && RENDERERS[wanted]) navigate(wanted);
  else navigate("home");

  updateMini();

  if (params.get("autoplay") === "1") startListening(allItems());

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}

init();
