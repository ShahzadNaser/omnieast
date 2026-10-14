(() => {
  if (window.__riyalSuffixFix) return;
  window.__riyalSuffixFix = true;

  const fixSuffix = (el) => {
    if (!el || el.querySelector("img")) return;
    const txt = (el.textContent || "").trim();
    if (!txt.startsWith("<img")) return;

    const tmp = document.createElement("div");
    tmp.innerHTML = txt;
    const src = tmp.querySelector("img")?.getAttribute("src") || "";
    if (!src.startsWith("/files/")) return;

    const img = document.createElement("img");
    img.src = src;
    img.style.cssText = "height:1.1em;width:1em;vertical-align:middle;";
    el.textContent = "";
    el.appendChild(img);
  };

  const scan = (node) => {
    if (!node || node.nodeType !== 1) return;
    if (node.matches(".grid-currency-suffix")) fixSuffix(node);
    node.querySelectorAll(".grid-currency-suffix").forEach(fixSuffix);
  };

  const start = () => {
    scan(document.body);
    new MutationObserver((mutations) => {
      for (const m of mutations) {
        const t = m.target.nodeType === 3 ? m.target.parentElement : m.target;
        const suffix = t && t.closest ? t.closest(".grid-currency-suffix") : null;
        if (suffix) fixSuffix(suffix);
        m.addedNodes.forEach(scan);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  };

  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
})();