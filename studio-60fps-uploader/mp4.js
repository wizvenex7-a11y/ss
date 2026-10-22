(function (root) {
  "use strict";

  const CONTAINERS = new Set(["moov", "trak", "mdia", "minf", "stbl", "dinf", "edts", "udta", "mvex"]);
  const METADATA = new Set(["udta", "meta"]);
  const PADDING = new Set(["free", "skip", "wide"]);

  const u32 = (b, o) => b[o] * 16777216 + (b[o + 1] << 16) + (b[o + 2] << 8) + b[o + 3];
  const u64 = (b, o) => u32(b, o) * 4294967296 + u32(b, o + 4);
  const fourcc = (b, o) => String.fromCharCode(b[o], b[o + 1], b[o + 2], b[o + 3]);

  function setU32(b, o, v) {
    b[o] = (v >>> 24) & 255;
    b[o + 1] = (v >>> 16) & 255;
    b[o + 2] = (v >>> 8) & 255;
    b[o + 3] = v & 255;
  }

  function setU64(b, o, v) {
    setU32(b, o, Math.floor(v / 4294967296));
    setU32(b, o + 4, v >>> 0);
  }

  async function read(file, start, end) {
    return new Uint8Array(await file.slice(start, end).arrayBuffer());
  }

  async function scanTop(file) {
    const boxes = [];
    let off = 0;
    while (off + 8 <= file.size) {
      const h = await read(file, off, Math.min(off + 16, file.size));
      let size = u32(h, 0);
      const type = fourcc(h, 4);
      let hdr = 8;
      if (size === 1) {
        size = u64(h, 8);
        hdr = 16;
      } else if (size === 0) {
        size = file.size - off;
      }
      if (size < hdr || off + size > file.size) {
        throw new Error(`Damaged MP4: box "${type}" at byte ${off} is cut off.`);
      }
      boxes.push({ type, start: off, size, hdr });
      off += size;
    }
    return boxes;
  }

  function parse(buf, start, end) {
    const out = [];
    let o = start;
    while (o + 8 <= end) {
      let size = u32(buf, o);
      const type = fourcc(buf, o + 4);
      let hdr = 8;
      if (size === 1) {
        size = u64(buf, o + 8);
        hdr = 16;
      } else if (size === 0) {
        size = end - o;
      }
      if (size < hdr || o + size > end) break;
      const box = { type, start: o, size, hdr };
      if (CONTAINERS.has(type)) box.children = parse(buf, o + hdr, o + size);
      out.push(box);
      o += size;
    }
    return out;
  }

  function walk(boxes, fn) {
    for (const box of boxes) {
      fn(box);
      if (box.children) walk(box.children, fn);
    }
  }

  const child = (box, type) => (box && box.children ? box.children.find((c) => c.type === type) : undefined);

  function timing(buf, box) {
    const o = box.start + box.hdr;
    return buf[o] === 1
      ? { timescale: u32(buf, o + 20), duration: u64(buf, o + 24) }
      : { timescale: u32(buf, o + 12), duration: u32(buf, o + 16) };
  }

  function describe(buf, moov) {
    const info = { duration: 0, video: null, audio: null };
    const mvhd = child(moov, "mvhd");
    if (mvhd) {
      const t = timing(buf, mvhd);
      if (t.timescale) info.duration = t.duration / t.timescale;
    }
    for (const trak of (moov.children || []).filter((c) => c.type === "trak")) {
      const mdia = child(trak, "mdia");
      const hdlr = child(mdia, "hdlr");
      const mdhd = child(mdia, "mdhd");
      const stbl = child(child(mdia, "minf"), "stbl");
      if (!hdlr || !mdhd || !stbl) continue;
      const kind = fourcc(buf, hdlr.start + hdlr.hdr + 8);
      const t = timing(buf, mdhd);
      const seconds = t.timescale ? t.duration / t.timescale : 0;
      const stsd = child(stbl, "stsd");
      const codec = stsd ? fourcc(buf, stsd.start + stsd.hdr + 12) : "?";
      if (kind === "vide" && !info.video) {
        let width = 0;
        let height = 0;
        const tkhd = child(trak, "tkhd");
        if (tkhd) {
          const o = tkhd.start + tkhd.hdr;
          const at = buf[o] === 1 ? 88 : 76;
          width = Math.round(u32(buf, o + at) / 65536);
          height = Math.round(u32(buf, o + at + 4) / 65536);
        }
        let samples = 0;
        const stts = child(stbl, "stts");
        if (stts) {
          const o = stts.start + stts.hdr;
          const n = u32(buf, o + 4);
          for (let i = 0; i < n && o + 16 + i * 8 <= stts.start + stts.size; i++) samples += u32(buf, o + 8 + i * 8);
        }
        info.video = { codec, width, height, fps: seconds ? samples / seconds : 0 };
      } else if (kind === "soun" && !info.audio) {
        info.audio = { codec };
      }
    }
    return info;
  }

  async function load(file) {
    const top = await scanTop(file);
    const moov = top.find((b) => b.type === "moov");
    if (!moov) throw new Error("This is not a complete MP4/MOV file (no moov index found).");
    const buf = await read(file, moov.start, moov.start + moov.size);
    const tree = parse(buf, 0, buf.length)[0];
    const mdat = top.find((b) => b.type === "mdat");
    const info = describe(buf, tree);
    info.size = file.size;
    info.bitrate = info.duration ? (file.size * 8) / info.duration : 0;
    info.moovFirst = !mdat || moov.start < mdat.start;
    info.fragmented = top.some((b) => b.type === "moof");
    let hasMetadata = false;
    walk([tree], (b) => {
      if (METADATA.has(b.type)) hasMetadata = true;
    });
    info.hasMetadata = hasMetadata;
    info.padding = top.filter((b) => PADDING.has(b.type)).length;
    return { top, moov, buf, tree, info };
  }

  function serialize(buf, box, drop) {
    if (!box.children) return [buf.subarray(box.start, box.start + box.size)];
    const parts = [];
    for (const c of box.children) {
      if (!drop.has(c.type)) parts.push(...serialize(buf, c, drop));
    }
    const head = new Uint8Array(8);
    setU32(head, 0, parts.reduce((sum, p) => sum + p.length, 8));
    head.set(buf.subarray(box.start + 4, box.start + 8), 4);
    return [head, ...parts];
  }

  function concat(parts) {
    const out = new Uint8Array(parts.reduce((sum, p) => sum + p.length, 0));
    let o = 0;
    for (const p of parts) {
      out.set(p, o);
      o += p.length;
    }
    return out;
  }

  async function analyze(file) {
    return (await load(file)).info;
  }

  async function prepare(file, options = {}) {
    const stripMetadata = options.stripMetadata !== false;
    const { top, moov, buf, tree, info } = await load(file);
    if (info.fragmented) {
      return { blob: file, info, changes: ["Fragmented MP4: left unchanged"] };
    }

    const newMoov = concat(serialize(buf, tree, stripMetadata ? METADATA : new Set()));
    const ftyp = top.filter((b) => b.type === "ftyp");
    const rest = top.filter((b) => b.type !== "ftyp" && b.type !== "moov" && !PADDING.has(b.type));
    const order = [...ftyp, moov, ...rest];

    const newStart = new Map();
    let pos = 0;
    for (const b of order) {
      newStart.set(b, pos);
      pos += b === moov ? newMoov.length : b.size;
    }

    const relocate = (off) => {
      const b = top.find((x) => x !== moov && off >= x.start && off < x.start + x.size);
      if (!b || !newStart.has(b)) throw new Error(`Chunk offset ${off} points outside the media data.`);
      return off - b.start + newStart.get(b);
    };

    walk(parse(newMoov, 0, newMoov.length), (box) => {
      if (box.type !== "stco" && box.type !== "co64") return;
      const o = box.start + box.hdr;
      const n = u32(newMoov, o + 4);
      const wide = box.type === "co64";
      for (let i = 0; i < n; i++) {
        const at = o + 8 + i * (wide ? 8 : 4);
        const moved = relocate(wide ? u64(newMoov, at) : u32(newMoov, at));
        if (wide) {
          setU64(newMoov, at, moved);
        } else {
          if (moved > 0xffffffff) throw new Error("File is too large to rearrange (over 4 GB with 32-bit offsets).");
          setU32(newMoov, at, moved);
        }
      }
    });

    const changes = [];
    if (!info.moovFirst) changes.push("Moved the video index (moov) to the start for fast processing");
    if (stripMetadata && info.hasMetadata) changes.push("Removed editor and device metadata");
    if (info.padding) changes.push(`Removed ${info.padding} empty padding box(es)`);
    if (!changes.length) changes.push("Already optimized, no changes needed");

    const blob = new Blob(
      order.map((b) => (b === moov ? newMoov : file.slice(b.start, b.start + b.size))),
      { type: "video/mp4" }
    );
    return { blob, info, changes };
  }

  const CODECS = {
    avc1: "H.264",
    avc3: "H.264",
    hvc1: "HEVC (H.265)",
    hev1: "HEVC (H.265)",
    av01: "AV1",
    vp09: "VP9",
    mp4a: "AAC",
    "ac-3": "AC-3",
    Opus: "Opus",
  };

  function report(info) {
    const v = info.video;
    const isH264 = !!v && (v.codec === "avc1" || v.codec === "avc3");
    return [
      { label: "Resolution", value: v ? `${v.width}x${v.height}` : "No video track", ok: !!v && Math.min(v.width, v.height) >= 1080 },
      { label: "Frame rate", value: v ? `${v.fps.toFixed(2)} fps` : "-", ok: !!v && v.fps >= 59 },
      { label: "Video codec", value: v ? CODECS[v.codec] || v.codec : "-", ok: isH264 },
      { label: "Bitrate", value: `${(info.bitrate / 1e6).toFixed(1)} Mbps`, ok: info.bitrate >= 10e6 },
      { label: "Audio", value: info.audio ? CODECS[info.audio.codec] || info.audio.codec : "None", ok: !!info.audio },
      { label: "Index at start", value: info.moovFirst ? "Yes" : "No", ok: info.moovFirst },
      { label: "Length", value: `${info.duration.toFixed(1)} s`, ok: true },
    ];
  }

  const api = { analyze, prepare, report };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StudioMP4 = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
