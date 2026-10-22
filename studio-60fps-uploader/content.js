(() => {
  "use strict";
  if (window.__studio60fps) return;
  window.__studio60fps = true;

  let settings = { autoPrepare: true, stripMetadata: true };
  chrome.storage.local.get(settings).then((s) => (settings = s));
  chrome.storage.onChanged.addListener((changes) => {
    for (const [key, { newValue }] of Object.entries(changes)) settings[key] = newValue;
  });

  let redispatching = false;
  const isVideo = (file) => file && (file.type.startsWith("video/") || /\.(mp4|mov|m4v)$/i.test(file.name));

  let panel;
  function showPanel(title, rows = [], notes = [], tone = "info") {
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "s60-panel";
      panel.setAttribute("role", "status");
      document.documentElement.appendChild(panel);
    }
    panel.replaceChildren();
    panel.dataset.tone = tone;

    const head = document.createElement("div");
    head.className = "s60-head";
    const name = document.createElement("strong");
    name.textContent = title;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "s60-close";
    close.setAttribute("aria-label", "Close");
    close.textContent = "\u00d7";
    close.addEventListener("click", () => panel.remove() || (panel = null));
    head.append(name, close);
    panel.append(head);

    if (rows.length) {
      const list = document.createElement("dl");
      list.className = "s60-rows";
      for (const row of rows) {
        const dt = document.createElement("dt");
        dt.textContent = row.label;
        const dd = document.createElement("dd");
        dd.textContent = row.value;
        dd.dataset.ok = String(row.ok);
        list.append(dt, dd);
      }
      panel.append(list);
    }
    for (const note of notes) {
      const p = document.createElement("p");
      p.className = "s60-note";
      p.textContent = note;
      panel.append(p);
    }
  }

  async function prepareFile(file) {
    showPanel("Preparing video...", [], [file.name], "busy");
    try {
      const { blob, info, changes } = await StudioMP4.prepare(file, { stripMetadata: settings.stripMetadata });
      const out = blob === file ? file : new File([blob], file.name, { type: "video/mp4", lastModified: Date.now() });
      showPanel("Video prepared", StudioMP4.report(info), changes, "ok");
      return out;
    } catch (err) {
      showPanel("Uploading the original file", [], [String(err.message || err)], "warn");
      return file;
    }
  }

  function handOver(input, file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    redispatching = true;
    try {
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    } finally {
      redispatching = false;
    }
  }

  window.addEventListener(
    "change",
    async (event) => {
      const input = event.target;
      if (redispatching || !(input instanceof HTMLInputElement) || input.type !== "file") return;
      const file = input.files && input.files[0];
      if (!isVideo(file)) return;
      if (!settings.autoPrepare) {
        StudioMP4.analyze(file)
          .then((info) => showPanel("Video check", StudioMP4.report(info), ["Auto-prepare is off."]))
          .catch(() => {});
        return;
      }
      event.stopImmediatePropagation();
      handOver(input, await prepareFile(file));
    },
    true
  );

  window.addEventListener(
    "drop",
    async (event) => {
      if (!settings.autoPrepare) return;
      const file = event.dataTransfer && event.dataTransfer.files[0];
      const input = document.querySelector('input[type="file"]');
      if (!isVideo(file) || !input) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      handOver(input, await prepareFile(file));
    },
    true
  );
})();
