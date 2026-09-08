/* Haber Akışı — Google Haberler bülteni + hands-free dinleme
 *
 * İki mod aynı veriyi paylaşır:
 *   1. Elle gezinme  — kartı kaydır / tıkla
 *   2. Hands-free    — sırayla seslendirir, okunan haber öne gelir
 *
 * Ses kaynağı: bültende hazır MP3 varsa o çalar (cue'larla senkron),
 * yoksa tarayıcının kendi Türkçe sesi (Web Speech API) devreye girer.
 * Böylece API anahtarı olmadan da hands-free çalışır.
 */
"use strict";

const DATA_URL = "data/latest.json";
const SAVED_KEY = "mynews:saved";
const RATE_KEY = "mynews:rate";

const $ = (sel) => document.querySelector(sel);

const el = {
  today: $("#today"),
  chips: $("#chips"),
  deck: $("#deck"),
  empty: $("#empty"),
  play: $("#btn-play"),
  next: $("#btn-next"),
  refresh: $("#btn-refresh"),
  searchBtn: $("#btn-search"),
  searchWrap: $("#search-wrap"),
  search: $("#search"),
  icoPlay: $("#ico-play"),
  icoPause: $("#ico-pause"),
  listenTitle: $("#listen-title"),
  listenSub: $("#listen-sub"),
  progress: $("#progress"),
  player: $("#player"),
};

const state = {
  bulletin: null,
  segment: "all",
  view: "feed",
  query: "",
  list: [],
  index: 0,
  playing: false,
  rate: Number(localStorage.getItem(RATE_KEY)) || 1,
  voice: null,
  saved: new Set(JSON.parse(localStorage.getItem(SAVED_KEY) || "[]")),
  wakeLock: null,
};

/* ---------------------------------------------------------------- yardımcı */

function relativeTime(hours) {
  if (hours == null) return "";
  if (hours < 1) return "az önce";
  if (hours < 24) return `${Math.round(hours)} saat önce`;
  const days = Math.round(hours / 24);
  return days === 1 ? "dün" : `${days} gün önce`;
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString("tr-TR", {
      day: "numeric", month: "long", year: "numeric",
    });
  } catch {
    return iso;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function persistSaved() {
  localStorage.setItem(SAVED_KEY, JSON.stringify([...state.saved]));
}

/* ------------------------------------------------------------------ veri */

async function loadBulletin() {
  const res = await fetch(DATA_URL, { cache: "no-cache" });
  if (!res.ok) throw new Error(`Bülten yüklenemedi (${res.status})`);
  return res.json();
}

function allItems() {
  if (!state.bulletin) return [];
  return state.bulletin.segments.flatMap((seg) =>
    seg.items.map((item) => ({ ...item, segment: seg.key, segmentTitle: seg.title }))
  );
}

function computeList() {
  let items = allItems();

  if (state.view === "saved") {
    items = items.filter((i) => state.saved.has(i.link));
  } else if (state.segment !== "all") {
    items = items.filter((i) => i.segment === state.segment);
  }

  if (state.query) {
    const q = state.query.toLocaleLowerCase("tr");
    items = items.filter(
      (i) =>
        i.title.toLocaleLowerCase("tr").includes(q) ||
        (i.publisher || "").toLocaleLowerCase("tr").includes(q)
    );
  }

  state.list = items;
  if (state.index >= items.length) state.index = 0;
}

/* --------------------------------------------------------------- arayüz */

function renderChips() {
  const segments = state.bulletin ? state.bulletin.segments : [];
  const chips = [{ key: "all", title: "Tümü" }, ...segments.map((s) => ({ key: s.key, title: s.title }))];

  el.chips.innerHTML = chips
    .map((c) => {
      const active = c.key === state.segment;
      const cls = active
        ? "bg-ink text-white"
        : "bg-white/70 text-ink-soft hover:bg-white";
      return `<button data-chip="${c.key}" class="shrink-0 rounded-full px-4 py-2 text-[14px] font-semibold shadow-deck backdrop-blur transition active:scale-95 ${cls}">${escapeHtml(c.title)}</button>`;
    })
    .join("");
}

function cardMarkup(item, position) {
  const saved = state.saved.has(item.link);
  const badge =
    item.source_count >= 3
      ? `<span class="inline-flex items-center gap-1 rounded-full bg-leaf-100 px-2.5 py-1 text-[12px] font-semibold text-leaf-700">
           <svg class="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2 4 5.5v6c0 4.7 3.4 9 8 10.5 4.6-1.5 8-5.8 8-10.5v-6z"/></svg>
           ${item.source_count} kaynak
         </span>`
      : `<span class="rounded-full bg-white px-2.5 py-1 text-[12px] font-medium text-ink-faint ring-1 ring-leaf-100">tek kaynak</span>`;

  const related = (item.related || [])
    .slice(0, 3)
    .map(
      (r) => `<li class="flex gap-2 text-[13px] leading-snug text-ink-soft">
                <span class="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-leaf-300"></span>
                <span class="min-w-0"><span class="font-medium text-ink">${escapeHtml(r.source)}</span> — ${escapeHtml(r.title)}</span>
              </li>`
    )
    .join("");

  const fallbackLogo = (item.publisher || "?").trim().charAt(0).toUpperCase();

  return `
  <article class="deck-card" data-state="${position}" data-link="${escapeHtml(item.link)}">
    <div class="rounded-xl2 bg-white p-5 shadow-card">
      <div class="flex items-center gap-3">
        <div class="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-full bg-leaf-100 text-[15px] font-bold text-leaf-700">
          <img src="${escapeHtml(item.favicon)}" alt="" loading="lazy"
               class="h-full w-full object-cover"
               onerror="this.replaceWith(document.createTextNode('${fallbackLogo}'))">
        </div>
        <div class="min-w-0 flex-1">
          <p class="truncate text-[15px] font-semibold">${escapeHtml(item.publisher)}</p>
          <p class="text-[13px] text-ink-faint">${relativeTime(item.age_hours)} · ${escapeHtml(item.segmentTitle)}</p>
        </div>
        <button data-act="save" aria-label="${saved ? "Kaydedilenlerden çıkar" : "Kaydet"}"
          class="grid h-10 w-10 shrink-0 place-items-center rounded-full transition active:scale-90 ${saved ? "bg-leaf-600 text-white" : "bg-leaf-50 text-ink-soft"}">
          <svg class="h-[18px] w-[18px]" fill="${saved ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.9" viewBox="0 0 24 24">
            <path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>

      <h2 class="mt-4 text-[21px] font-bold leading-[1.28] tracking-tight">${escapeHtml(item.title)}</h2>

      <div class="mt-3 flex items-center gap-2">${badge}</div>

      ${related ? `<ul class="mt-4 space-y-2 border-t border-leaf-100 pt-4">${related}</ul>` : ""}

      <div class="mt-5 flex items-center gap-2">
        <button data-act="speak"
          class="inline-flex flex-1 items-center justify-center gap-2 rounded-full bg-leaf-600 px-4 py-3 text-[14px] font-semibold text-white transition active:scale-[.98]">
          <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5.5v13l11-6.5z"/></svg>
          Bu haberi oku
        </button>
        <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer"
          class="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-leaf-50 text-ink-soft transition active:scale-95" aria-label="Kaynağa git">
          <svg class="h-[18px] w-[18px]" fill="none" stroke="currentColor" stroke-width="1.9" viewBox="0 0 24 24">
            <path d="M14 5h5v5M19 5l-8.5 8.5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M18 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4" stroke-linecap="round"/>
          </svg>
        </a>
      </div>
    </div>
  </article>`;
}

function stubMarkup(item) {
  const fallbackLogo = (item.publisher || "?").trim().charAt(0).toUpperCase();
  return `
  <article class="deck-card" data-state="behind">
    <div class="rounded-xl2 bg-white/95 px-5 py-4 shadow-deck">
      <div class="flex items-center gap-3">
        <div class="grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-full bg-leaf-100 text-[13px] font-bold text-leaf-700">
          <img src="${escapeHtml(item.favicon)}" alt="" loading="lazy" class="h-full w-full object-cover"
               onerror="this.replaceWith(document.createTextNode('${fallbackLogo}'))">
        </div>
        <p class="min-w-0 flex-1 truncate text-[14px] font-semibold text-ink-soft">${escapeHtml(item.publisher)}</p>
        <span class="shrink-0 text-[12px] text-ink-faint">${relativeTime(item.age_hours)}</span>
      </div>
    </div>
  </article>`;
}

function renderDeck() {
  computeList();

  if (!state.list.length) {
    el.deck.innerHTML = "";
    el.empty.classList.remove("hidden");
    el.empty.textContent =
      state.view === "saved"
        ? "Henüz haber kaydetmediniz. Kartlardaki yer imi düğmesini kullanın."
        : "Bu filtrede haber yok.";
    return;
  }
  el.empty.classList.add("hidden");

  // Öndeki kart tam gövde, arkadakiler yalnızca ince şerit.
  const front = state.list[state.index];
  const behind = state.list.slice(state.index + 1, state.index + 3);

  el.deck.innerHTML =
    behind.map((item) => stubMarkup(item)).join("") + cardMarkup(front, "front");

  el.deck.querySelectorAll('[data-state="behind"]').forEach((node, i) => {
    const depth = i + 1;
    node.style.transform = `translateY(${32 - 13 * depth}px) scale(${1 - 0.05 * depth})`;
    node.style.opacity = String(1 - 0.28 * depth);
  });

  const frontNode = el.deck.querySelector('[data-state="front"]');
  if (frontNode && state.playing) frontNode.firstElementChild.classList.add("speaking");

  updateStatus();
}

function updateStatus() {
  const total = state.list.length;
  const current = state.list[state.index];
  el.listenTitle.textContent = state.playing && current ? current.publisher : "Sesli bülten";
  el.listenSub.textContent = total
    ? `${state.index + 1} / ${total} · ${state.playing ? "okunuyor" : "otomatik okur"}`
    : "haber yok";
  el.progress.style.width = total ? `${((state.index + (state.playing ? 1 : 0)) / total) * 100}%` : "0%";

  el.icoPlay.classList.toggle("hidden", state.playing);
  el.icoPause.classList.toggle("hidden", !state.playing);
  el.play.setAttribute("aria-label", state.playing ? "Duraklat" : "Sesli dinlemeyi başlat");
}

function setNav(view) {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    const active = btn.dataset.view === view;
    btn.classList.toggle("bg-leaf-600", active);
    btn.classList.toggle("text-white", active);
    btn.classList.toggle("text-ink-soft", !active);
  });
}

/* -------------------------------------------------------------- konuşma */

function pickVoice() {
  const voices = speechSynthesis.getVoices();
  if (!voices.length) return null;
  return (
    voices.find((v) => v.lang === "tr-TR") ||
    voices.find((v) => v.lang && v.lang.toLowerCase().startsWith("tr")) ||
    null
  );
}

function initVoices() {
  state.voice = pickVoice();
  if (!state.voice && "onvoiceschanged" in speechSynthesis) {
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

/* Bir haber bitince sıradakine geç. Her iki ses kaynağı da bunu çağırır. */
function advance() {
  if (!state.playing) return;
  if (state.index >= state.list.length - 1) return stop(true);
  state.index += 1;
  renderDeck();
  playCurrent();
}

/* Hazır ses dosyası varsa onu çal, yoksa tarayıcının Türkçe sesine düş. */
function playCurrent() {
  const item = state.list[state.index];
  if (!item) return stop();

  if ("speechSynthesis" in window) speechSynthesis.cancel();
  el.player.pause();

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
    el.listenSub.textContent = "Bu tarayıcı seslendirmeyi desteklemiyor.";
    state.playing = false;
    return updateStatus();
  }

  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(item.speech || item.title);
  utter.lang = "tr-TR";
  utter.rate = state.rate;
  utter.pitch = 1;
  if (state.voice) utter.voice = state.voice;

  utter.onend = advance;
  utter.onerror = (event) => {
    // "interrupted" bizim cancel çağrımızdır, hata sayılmaz.
    if (event.error && event.error !== "interrupted" && event.error !== "canceled") {
      console.warn("Seslendirme hatası:", event.error);
      stop();
    }
  };

  speechSynthesis.speak(utter);
  startKeepAlive();
}

async function requestWakeLock() {
  try {
    if ("wakeLock" in navigator) state.wakeLock = await navigator.wakeLock.request("screen");
  } catch {
    /* pil tasarrufu modunda reddedilebilir, önemli değil */
  }
}

function releaseWakeLock() {
  if (state.wakeLock) {
    state.wakeLock.release().catch(() => {});
    state.wakeLock = null;
  }
}

function play() {
  if (!state.list.length) return;
  state.playing = true;
  requestWakeLock();
  playCurrent();
  renderDeck();
}

function stop(finished = false) {
  state.playing = false;
  stopKeepAlive();
  releaseWakeLock();
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  el.player.onended = null;
  el.player.pause();
  if (finished) state.index = 0;
  renderDeck();
}

function toggle() {
  state.playing ? stop() : play();
}

function next() {
  if (state.index < state.list.length - 1) {
    state.index += 1;
  } else {
    state.index = 0;
  }
  renderDeck();
  if (state.playing) playCurrent();
}

function prev() {
  state.index = state.index > 0 ? state.index - 1 : 0;
  renderDeck();
  if (state.playing) playCurrent();
}

/* ------------------------------------------------------------- etkileşim */

el.play.addEventListener("click", toggle);
el.next.addEventListener("click", next);

el.refresh.addEventListener("click", async () => {
  el.refresh.classList.add("animate-spin");
  try {
    state.bulletin = await loadBulletin();
    state.index = 0;
    renderChips();
    renderDeck();
  } catch (err) {
    el.listenSub.textContent = err.message;
  } finally {
    el.refresh.classList.remove("animate-spin");
  }
});

el.searchBtn.addEventListener("click", () => {
  el.searchWrap.classList.toggle("hidden");
  if (!el.searchWrap.classList.contains("hidden")) el.search.focus();
  else {
    el.search.value = "";
    state.query = "";
    renderDeck();
  }
});

el.search.addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  state.index = 0;
  renderDeck();
});

el.chips.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-chip]");
  if (!btn) return;
  state.segment = btn.dataset.chip;
  state.index = 0;
  renderChips();
  renderDeck();
  if (state.playing) playCurrent();
});

el.deck.addEventListener("click", (event) => {
  const card = event.target.closest(".deck-card");
  if (!card || card.dataset.state !== "front") return;

  const action = event.target.closest("[data-act]");
  if (!action) return;

  if (action.dataset.act === "save") {
    const link = card.dataset.link;
    state.saved.has(link) ? state.saved.delete(link) : state.saved.add(link);
    persistSaved();
    renderDeck();
  }

  if (action.dataset.act === "speak") {
    state.playing = true;
    requestWakeLock();
    playCurrent();
    renderDeck();
  }
});

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.view;
    setNav(view);

    if (view === "listen") {
      state.view = "feed";
      state.index = 0;
      renderDeck();
      if (!state.playing) play();
      return;
    }
    if (view === "about") {
      state.view = "feed";
      showAbout();
      return;
    }
    state.view = view;
    state.index = 0;
    renderDeck();
  });
});

function showAbout() {
  const b = state.bulletin;
  const health = (b?.health || [])
    .map(
      (h) =>
        `<li class="flex justify-between gap-3 text-[13px]"><span class="text-ink-soft">${h.topic}</span>
         <span class="${h.status === "ok" ? "text-leaf-700" : "text-red-600"} font-semibold">${h.status} · ${h.count}</span></li>`
    )
    .join("");

  el.empty.classList.add("hidden");
  el.deck.innerHTML = `
    <article class="deck-card" data-state="front">
      <div class="rounded-xl2 bg-white p-5 shadow-card">
        <h2 class="text-[20px] font-bold tracking-tight">Bu bülten nasıl hazırlanıyor?</h2>
        <p class="mt-3 text-[14px] leading-relaxed text-ink-soft">
          Haberler Google Haberler RSS akışlarından (Türkiye, Bilim &amp; Teknoloji, Spor) alınıyor.
          Bir olayı <strong class="text-ink">kaç farklı yayıncının</strong> yazdığı önem sinyali olarak
          kullanılıyor; canlı maç anlatımı gibi kalıplar ve tıklama tuzağı başlıklar eleniyor.
        </p>
        <p class="mt-3 text-[14px] leading-relaxed text-ink-soft">
          Seslendirme başlıklarla sınırlı: RSS makale gövdesi vermediği için
          metin uydurulmuyor, yalnızca başlık ve kaynak okunuyor.
        </p>
        <ul class="mt-4 space-y-2 border-t border-leaf-100 pt-4">${health}</ul>
        <p class="mt-4 text-[12px] text-ink-faint">Bülten tarihi: ${b ? formatDate(b.generated_at) : "-"}</p>
      </div>
    </article>`;
}

/* Kaydırma ile gezinme */
let touchX = null;
let touchY = null;
el.deck.addEventListener("pointerdown", (e) => {
  touchX = e.clientX;
  touchY = e.clientY;
});
el.deck.addEventListener("pointerup", (e) => {
  if (touchX === null) return;
  const dx = e.clientX - touchX;
  const dy = e.clientY - touchY;
  touchX = touchY = null;
  if (Math.abs(dx) < 55 || Math.abs(dy) > Math.abs(dx)) return;
  dx < 0 ? next() : prev();
});

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.code === "Space") { e.preventDefault(); toggle(); }
  if (e.code === "ArrowRight") next();
  if (e.code === "ArrowLeft") prev();
});

// Sekme arka plana alınınca konuşma bozulabilir; düzgünce durdur.
document.addEventListener("visibilitychange", () => {
  const current = state.list[state.index];
  if (document.hidden && state.playing && !(current && current.audio)) stop();
});

/* ------------------------------------------------------------- başlangıç */

async function init() {
  setNav("feed");
  initVoices();

  try {
    state.bulletin = await loadBulletin();
  } catch (err) {
    el.listenSub.textContent = err.message;
    el.empty.classList.remove("hidden");
    el.empty.textContent = "Bülten yüklenemedi. Yenile düğmesini deneyin.";
    return;
  }

  el.today.textContent = formatDate(state.bulletin.generated_at);
  renderChips();
  renderDeck();
  el.listenSub.textContent = `${state.bulletin.total} haber · otomatik okur`;

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

init();
