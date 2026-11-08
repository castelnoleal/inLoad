/*
 * inLoad ad slots — house ads for MEIOCG products and instApped.
 * Edit this list to change what appears. Each ad:
 *   name, tagline, url, cta, icon (2–3 letters), color (hex)
 * Slots:  #adBanner (rotating top strip) · [data-ad-slot="inline"] · #adGrid (footer grid)
 */
window.INLOAD_ADS = [
  {
    name: "Duel Synapse: KodeX",
    tagline: "Yu-Gi-Oh! card database & rulings in your pocket. Coming to Google Play.",
    url: "https://meiocg.org/duelsynapse",
    cta: "Try KodeX",
    icon: "KX",
    color: "#7c9cff"
  },
  {
    name: "instApped",
    tagline: "Turn any website, HTML or ZIP into an Android app — APK & AAB in minutes.",
    url: "https://create.instapped.com",
    cta: "Build an app",
    icon: "iA",
    color: "#ffb547"
  },
  {
    name: "Meta Insider OCG",
    tagline: "Yu-Gi-Oh! OCG news, decklists and the meta from the Philippines.",
    url: "https://meiocg.org",
    cta: "Visit MEIOCG",
    icon: "ME",
    color: "#ff6fa8"
  },
  {
    name: "MEIOCG Price Guide",
    tagline: "Check OCG card prices with price history before you buy or trade.",
    url: "https://meiocg.org/prices",
    cta: "Check prices",
    icon: "₱",
    color: "#22d3a6"
  },
  {
    name: "Duel Synapse Calculator",
    tagline: "Duel timer and LP calculator for your Yu-Gi-Oh! games.",
    url: "https://meiocg.org/duelsynapse",
    cta: "Open",
    icon: "LP",
    color: "#b58cff"
  }
];

(function () {
  const ADS = window.INLOAD_ADS || [];
  if (!ADS.length) return;

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const link = (ad, cls, inner) =>
    `<a class="${cls}" href="${esc(ad.url)}" target="_blank" rel="noopener sponsored" style="--ad-color:${esc(ad.color)}">${inner}</a>`;
  const icon = (ad) => `<span class="ad-icon">${esc(ad.icon)}</span>`;

  // Top rotating banner
  const banner = document.getElementById("adBanner");
  if (banner) {
    let i = Math.floor(Math.random() * ADS.length);
    const show = () => {
      const ad = ADS[i % ADS.length];
      banner.innerHTML =
        link(ad, "", `${icon(ad)}<span class="ad-text"><b>${esc(ad.name)}</b><span>${esc(ad.tagline)}</span></span><span class="ad-cta">${esc(ad.cta)}</span>`) +
        `<span class="ad-tag">Ad</span>`;
      i++;
    };
    show();
    setInterval(() => { if (!document.hidden) show(); }, 7000);
  }

  const card = (ad) =>
    link(ad, "ad-card", `${icon(ad)}<span class="ad-text"><b>${esc(ad.name)}</b><span>${esc(ad.tagline)}</span></span><span class="go">${esc(ad.cta)} →</span><span class="ad-tag">Sponsored</span>`);

  // Inline slots: a different ad in each
  const slots = document.querySelectorAll('[data-ad-slot="inline"]');
  const order = ADS.map((_, k) => k).sort(() => Math.random() - 0.5);
  slots.forEach((el, k) => { el.innerHTML = card(ADS[order[k % order.length]]); });

  // Footer grid: everything
  const grid = document.getElementById("adGrid");
  if (grid) grid.innerHTML = ADS.map(card).join("");
})();
