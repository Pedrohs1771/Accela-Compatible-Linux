(function () {
  const BRIDGE = "http://127.0.0.1:32175";
  const ROOT_ID = "lumatools-companion-root";

  function ensureRoot() {
    let root = document.getElementById(ROOT_ID);
    if (root) return root;

    root = document.createElement("div");
    root.id = ROOT_ID;
    root.innerHTML = `
      <button class="luma-steam-button" type="button">LumaTools</button>
      <div class="luma-steam-panel" hidden>
        <div class="luma-steam-title">LumaTools</div>
        <div class="luma-steam-status">conectando...</div>
        <button class="luma-steam-open" type="button">Abrir app</button>
      </div>
    `;
    document.body.appendChild(root);

    root.querySelector(".luma-steam-button").addEventListener("click", () => {
      const panel = root.querySelector(".luma-steam-panel");
      panel.hidden = !panel.hidden;
      refresh(root);
    });
    root.querySelector(".luma-steam-open").addEventListener("click", () => {
      fetch(`${BRIDGE}/show`, { method: "POST" }).catch(() => {});
    });
    return root;
  }

  async function refresh(root) {
    const status = root.querySelector(".luma-steam-status");
    try {
      const response = await fetch(`${BRIDGE}/status`, { cache: "no-store" });
      const data = await response.json();
      if (!data.ok) throw new Error("bridge offline");

      root.style.setProperty("--luma-accent", data.accent_color || "#C06C84");
      const line = data.busy
        ? `baixando ${data.current_game || data.current_job || "item"}`
        : "pronto";
      status.textContent = `${line} | fila ${data.queue_count} | libs ${data.steam_libraries.length}`;
    } catch (_err) {
      status.textContent = "LumaTools não está aberto";
    }
  }

  function boot() {
    const root = ensureRoot();
    refresh(root);
    window.setInterval(() => refresh(root), 5000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
