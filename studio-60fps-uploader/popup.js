const DEFAULTS = { autoPrepare: true, stripMetadata: true };

chrome.storage.local.get(DEFAULTS).then((settings) => {
  for (const key of Object.keys(DEFAULTS)) {
    const box = document.getElementById(key);
    box.checked = settings[key];
    box.addEventListener("change", () => chrome.storage.local.set({ [key]: box.checked }));
  }
});

document.getElementById("openTool").addEventListener("click", () => {
  chrome.tabs.create({ url: chrome.runtime.getURL("patcher.html") });
});
