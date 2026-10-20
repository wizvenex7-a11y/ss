// ==UserScript==
// @name         ElevenLabs Word SRT Recorder
// @namespace    venex.srt
// @version      2.2
// @description  Tracks #0447ff (current) and #121213 (played) words during playback with real time and saves a word-by-word SRT
// @match        https://elevenlabs.io/*
// @match        https://*.elevenlabs.io/*
// @run-at       document-start
// @grant        none
// @downloadURL  https://raw.githubusercontent.com/wizvenex7-a11y/ss/main/elevenlabs-srt-recorder.user.js
// @updateURL    https://raw.githubusercontent.com/wizvenex7-a11y/ss/main/elevenlabs-srt-recorder.user.js
// ==/UserScript==

(function () {
  'use strict';

  const BLUE = 'rgb(4, 71, 255)';
  const IDLE_FINISH_MS = 8000;

  const media = new Set();
  const origPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    media.add(this);
    try { onPlay(); } catch (e) {}
    return origPlay.apply(this, arguments);
  };

  let wa = null;
  const origStart = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function (when = 0, offset = 0, ...r) {
    const ctx = this.context;
    const rec = { ctx, at: Math.max(when, ctx.currentTime), offset: offset || 0, stopped: false };
    wa = rec;
    this.addEventListener('ended', () => { rec.stopped = true; });
    try { onPlay(); } catch (e) {}
    return origStart.call(this, when, offset, ...r);
  };

  let source = '-';
  function now() {
    for (const m of media) if (!m.paused && !m.ended) { source = 'media'; return m.currentTime; }
    if (wa && !wa.stopped && wa.ctx.state === 'running') { source = 'webaudio'; return wa.offset + wa.ctx.currentTime - wa.at; }
    for (const m of document.querySelectorAll('audio,video')) if (!m.paused) { source = 'media'; return m.currentTime; }
    return null;
  }

  const pad = (n, l = 2) => String(n).padStart(l, '0');
  const ts = s => { const ms = Math.max(0, Math.round(s * 1000));
    return `${pad(Math.floor(ms / 3600000))}:${pad(Math.floor(ms / 60000) % 60)}:${pad(Math.floor(ms / 1000) % 60)},${pad(ms % 1000, 3)}`; };
  const short = s => ts(s).slice(3);

  let lastFileName = '';
  document.addEventListener('change', e => {
    const f = e.target && e.target.files && e.target.files[0];
    if (f) { lastFileName = f.name; if (ui) ui.file.textContent = 'File: ' + f.name; }
  }, true);
  document.addEventListener('drop', e => {
    const f = e.dataTransfer && e.dataTransfer.files[0];
    if (f) { lastFileName = f.name; if (ui) ui.file.textContent = 'File: ' + f.name; }
  }, true);
  const fileBase = () => (lastFileName || 'transcript').replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|]/g, '_');

  let words = [], lastEl = null, recording = false, lastSeen = 0;

  function onPlay() {
    if (recording) return;
    words = []; lastIdx = -1; spans = []; recording = true; lastSeen = performance.now();
    renderAll(); setStatus('Recording...', '#7aa2ff');
    requestAnimationFrame(loop);
  }

  const DARK = 'rgb(18, 18, 19)';          // #121213 = already spoken
  const isHit = c => c === BLUE || c === DARK;

  // All transcript word spans in order (leaf spans that are blue, dark, or another text color)
  function wordSpans() {
    const out = [];
    for (const s of document.querySelectorAll('span')) {
      if (s.children.length || !s.textContent.trim()) continue;
      if (ui && ui.root.contains(s)) continue;
      out.push(s);
    }
    // keep only the transcript container: the parent that holds the blue/dark word
    const ref = out.find(s => isHit(getComputedStyle(s).color) && getComputedStyle(s).color === BLUE) ||
                out.find(s => getComputedStyle(s).color === DARK);
    if (!ref) return [];
    let box = ref.parentElement;
    while (box && box.querySelectorAll('span').length < 20 && box.parentElement) box = box.parentElement;
    return out.filter(s => box.contains(s));
  }

  // progress = index of last word that is blue (current) or #121213 (played)
  let spans = [], lastIdx = -1, lastT = 0, rescan = 0;
  // App editor page (elevenlabs.io/app/speech-to-text): <span data-type="word" class="text-foreground|text-secondary">
  function appSpans() {
    return [...document.querySelectorAll('span[data-type="word"]')]
      .filter(s => s.textContent.trim() && !(ui && ui.root.contains(s)));
  }
  const appPlayed = s => s.classList.contains('text-foreground') || /text-shadow/.test(s.className) ||
    isHit(getComputedStyle(s).color);
  let appMode = false;
  function progress() {
    if (!spans.length || performance.now() - rescan > 1500) {
      const a = appSpans();
      appMode = a.length > 0;
      spans = appMode ? a : wordSpans();
      rescan = performance.now();
    }
    if (appMode) {
      let idx = -1, act = false;
      for (let i = 0; i < spans.length; i++) {
        if (/text-shadow/.test(spans[i].className)) { idx = i; act = true; break; }
        if (appPlayed(spans[i])) idx = i;
      }
      return { idx, blue: act || idx >= 0 };
    }
    let idx = -1, blueIdx = -1;
    for (let i = 0; i < spans.length; i++) {
      const c = getComputedStyle(spans[i]).color;
      if (c === BLUE) { blueIdx = i; idx = i; }
      else if (c === DARK) idx = i;
    }
    return { idx: blueIdx >= 0 ? blueIdx : idx, blue: blueIdx >= 0 };
  }

  function loop() {
    if (!recording) return;
    const t = now();
    const p = progress();
    if (t !== null && p.idx > lastIdx) {
      // words skipped between frames get evenly spread times
      const from = lastIdx + 1, n = p.idx - from + 1;
      const t0 = words.length ? Math.max(lastT, words[words.length - 1].start) : t;
      for (let i = 0; i < n; i++) {
        const st = n === 1 ? t : t0 + (t - t0) * (i + 1) / n;
        const prev = words[words.length - 1];
        if (prev && prev.end <= prev.start) prev.end = st;
        const w = { text: spans[from + i].textContent.trim(), start: st, end: st };
        words.push(w); addRow(w, words.length);
      }
      lastIdx = p.idx;
    } else if (t !== null && !p.blue && words.length) {
      const prev = words[words.length - 1];
      if (prev.end <= prev.start && lastIdx >= 0) prev.end = t;
    }
    if (t !== null) { lastT = t; lastSeen = performance.now(); }
    const ended = [...media].some(m => m.ended) || (wa && wa.stopped && t === null);
    if (words.length && (ended || performance.now() - lastSeen > IDLE_FINISH_MS)) return finish();
    setStatus(`Recording... ${words.length} words | ${t !== null ? short(t) : 'paused'} | src: ${source}${appMode ? ' | app' : ''}`, '#7aa2ff');
    requestAnimationFrame(loop);
  }

  function buildSRT() {
    return words.map((w, i) => {
      const end = w.end > w.start ? w.end : w.start + 0.4;
      return `${i + 1}\n${ts(w.start)} --> ${ts(end)}\n${w.text}\n`;
    }).join('\n');
  }

  function finish() {
    recording = false;
    if (!words.length) return setStatus('No words captured', '#e5484d');
    const last = words[words.length - 1];
    if (last.end <= last.start) last.end = last.start + 0.5;
    refreshTimes();
    saveSRT();
  }

  function saveSRT() {
    if (!words.length) return setStatus('Nothing to save', '#e5484d');
    const name = fileBase() + '.srt';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([buildSRT()], { type: 'text/plain;charset=utf-8' }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
    ui.out.textContent = 'Saved: ' + name + ' (' + words.length + ' words)';
    setStatus('Done', '#30a46c');
  }

  let ui = null;
  function buildUI() {
    if (ui || !document.body || !document.head) return;
    const root = document.createElement('div');
    root.id = 'vx-srt';
    root.innerHTML = `
      <div class="h"><b>Word SRT Recorder</b><span class="x">_</span></div>
      <div class="b">
        <div class="st">Waiting for PLAY...</div>
        <div class="f">File: -</div>
        <div class="list"></div>
        <div class="btns">
          <button data-a="save">Save SRT</button>
          <button data-a="stop">Stop</button>
          <button data-a="copy">Copy</button>
          <button data-a="clear">Clear</button>
        </div>
        <div class="o">No file saved yet</div>
      </div>`;
    const css = document.createElement('style');
    css.textContent = `
      #vx-srt{position:fixed;right:16px;bottom:16px;width:320px;z-index:2147483647;background:#111;color:#eee;
        font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;border:1px solid #333;border-radius:10px;box-shadow:0 8px 30px #0008;overflow:hidden}
      #vx-srt .h{display:flex;justify-content:space-between;align-items:center;padding:8px 10px;background:#0447ff;color:#fff;cursor:move;user-select:none}
      #vx-srt .x{cursor:pointer;padding:0 6px;font-weight:bold}
      #vx-srt .b{padding:8px 10px;display:flex;flex-direction:column;gap:6px}
      #vx-srt.min .b{display:none}
      #vx-srt .st{font-weight:bold}
      #vx-srt .f{color:#aaa;word-break:break-all}
      #vx-srt .o{color:#30a46c;word-break:break-all}
      #vx-srt .list{max-height:260px;overflow:auto;background:#000;border:1px solid #222;border-radius:6px;padding:4px}
      #vx-srt .r{display:flex;gap:8px;padding:2px 4px;border-radius:4px}
      #vx-srt .r:last-child{background:#0447ff33}
      #vx-srt .r .t{color:#7aa2ff;flex:none}
      #vx-srt .btns{display:flex;gap:6px}
      #vx-srt button{flex:1;background:#222;color:#eee;border:1px solid #444;border-radius:6px;padding:5px 0;cursor:pointer;font:inherit}
      #vx-srt button:hover{background:#0447ff;border-color:#0447ff}`;
    document.head.appendChild(css);
    document.body.appendChild(root);
    ui = { root, st: root.querySelector('.st'), file: root.querySelector('.f'),
           list: root.querySelector('.list'), out: root.querySelector('.o') };
    if (lastFileName) ui.file.textContent = 'File: ' + lastFileName;

    root.querySelector('.x').onclick = () => root.classList.toggle('min');
    root.querySelector('.btns').onclick = e => {
      const a = e.target.dataset.a;
      if (a === 'save') { if (recording) finish(); else saveSRT(); }
      if (a === 'stop') finish();
      if (a === 'copy') navigator.clipboard.writeText(buildSRT()).then(() => setStatus('SRT copied', '#30a46c'));
      if (a === 'clear') { recording = false; words = []; renderAll(); ui.out.textContent = 'No file saved yet'; setStatus('Waiting for PLAY...', '#eee'); }
    };

    const h = root.querySelector('.h');
    h.onmousedown = e => {
      if (e.target.classList.contains('x')) return;
      const r = root.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      const mv = ev => { root.style.left = ev.clientX - dx + 'px'; root.style.top = ev.clientY - dy + 'px'; root.style.right = 'auto'; root.style.bottom = 'auto'; };
      const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    };
  }

  function setStatus(t, c) { if (!ui) return; ui.st.textContent = t; ui.st.style.color = c; }
  function addRow(w, i) {
    if (!ui) return;
    const r = document.createElement('div'); r.className = 'r';
    const a = document.createElement('span'); a.className = 't'; a.textContent = `${i}. ${short(w.start)}`;
    const b = document.createElement('span'); b.textContent = w.text;
    r.append(a, b); ui.list.appendChild(r); ui.list.scrollTop = ui.list.scrollHeight;
  }
  function renderAll() { if (!ui) return; ui.list.innerHTML = ''; words.forEach((w, i) => addRow(w, i + 1)); }
  function refreshTimes() {
    if (!ui) return;
    [...ui.list.children].forEach((r, i) => {
      const w = words[i];
      if (w) r.firstChild.textContent = `${i + 1}. ${short(w.start)} → ${short(w.end)}`;
    });
  }

  const ensure = () => { if (!document.getElementById('vx-srt')) { ui = null; buildUI(); renderAll(); } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensure); else ensure();
  setInterval(ensure, 2000);
})();
