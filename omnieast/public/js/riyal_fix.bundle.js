(() => {
  if (window.__riyalSuffixFix) return;
  window.__riyalSuffixFix = true;

  // Shrink the space Frappe reserved for the symbol to the real image width
  const resetWidth = (el) => {
    const wrapper = el.closest(".grid-currency-input");
    if (!wrapper) return;
    const w = el.getBoundingClientRect().width;
    wrapper.style.setProperty(
      "--grid-currency-symbol-width",
      w > 0 ? w + "px" : "1.2em"
    );
  };

  const fixSuffix = (el) => {
    if (!el) return;

    // Already fixed: only make sure the reserved width is correct
    if (el.querySelector("img")) {
      resetWidth(el);
      return;
    }

    const txt = (el.textContent || "").trim();
    if (!txt.startsWith("<img")) return;   // normal symbols are left untouched

    const tmp = document.createElement("div");
    tmp.innerHTML = txt;
    const src = tmp.querySelector("img")?.getAttribute("src") || "";
    if (!src.startsWith("/files/")) return;

    const img = document.createElement("img");
    img.src = src;
    img.style.cssText = "height:1.1em;width:1em;vertical-align:middle;";
    el.textContent = "";
    el.appendChild(img);

    resetWidth(el);
    requestAnimationFrame(() => resetWidth(el));   // re-check after layout
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