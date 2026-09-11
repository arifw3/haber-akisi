/** Tailwind yapılandırması.
 *
 * Eskiden bu blok index.html içinde satır içiydi ve stiller
 * cdn.tailwindcss.com tarafından TARAYICIDA derleniyordu: 407 KB'lık bir
 * betik, her açılışta CSS üretimi ve üçüncü taraf bir bağımlılık. CDN
 * yavaşladığında uygulama stilsiz açılıyordu.
 *
 * Artık CSS burada, yayın öncesi bir kez derleniyor.
 */
module.exports = {
  content: ["./site/index.html", "./site/app.js"],
  theme: {
    extend: {
      colors: {
        /* Sıcak nötrler: gri yerine pembeye çalan koyu tonlar */
        ink: { DEFAULT: "#2a1020", soft: "#7b5164", faint: "#b189a0" },
        brand: { 50: "#fff0f6", 100: "#ffe0ec", 200: "#ffc4dc", 500: "#f0508f", 600: "#d81b60", 700: "#ab134b" },
        shell: "#fdeef4",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      boxShadow: {
        hero: "0 22px 44px -20px rgba(120,18,60,.42)",
        card: "0 10px 30px -18px rgba(120,18,60,.24)",
        nav: "0 -4px 30px -12px rgba(120,18,60,.16)",
        pill: "0 10px 22px -10px rgba(216,27,96,.55)",
      },
      borderRadius: { xl2: "1.5rem", xl3: "2rem" },
    },
  },
};
