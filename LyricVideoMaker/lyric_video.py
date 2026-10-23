#!/usr/bin/env python3
"""
Lyric video maker for Arabic and English SRT files, with big animated emoji.
(Pillow frames -> ffmpeg H.264, always 16:9, 60 fps)

Templates:
    --style mono     black / white flashing lines, condensed words that slide in one by one,
                     glow and motion echo on black
    --style classic  the colored kinetic style (stack, giant, script, outline ghost text)
                     with a light/dark color set (--palette)

Languages:
    --lang ar        Arabic fonts, letters joined, right-to-left layout and motion
    --lang en        English fonts, left-to-right

Quality (size): --quality 720p | fhd | 2k | 4k   (1280x720 ... 3840x2160)

Usage (Windows): double-click "Make Lyric Video.bat".
Usage (command line):
    pip install -r requirements.txt
    python lyric_video.py --lang en --style mono --quality fhd
    python lyric_video.py --lang ar --style classic --palette gold --srt song.srt --audio song.mp3

Emoji: put any emoji in the lyrics, e.g. "my heart ❤️🔥". They pop in on their word,
bounce and float, in the lyric color (--original-emoji keeps their own colors).

SRT style tags (optional, at the very start of a cue's text):
    {small} {stack} {giant} {script} {blank}   layout (classic; in mono, giant = big words)
    {dark} / {light}            background for this cue (default: alternates every line)
    {ghost=WORD} / {noghost}    outline text behind the lyrics (classic)
    {noemoji}                   hide the floating emoji copies for this cue
Inline timing: put <00:00:02,420> before a word to set exactly when it appears.
"""

import argparse
import math
import os
import random
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont

try:
    import arabic_reshaper
except ImportError:
    sys.exit("Missing package: run  pip install -r requirements.txt  (arabic-reshaper)")
try:
    from bidi import get_display
except ImportError:
    try:
        from bidi.algorithm import get_display
    except ImportError:
        sys.exit("Missing package: run  pip install -r requirements.txt  (python-bidi)")

GOOGLE_FONTS = "https://raw.githubusercontent.com/google/fonts/main/ofl"
FONT_SETS = {
    "ar": {
        "bold": ("Tajawal-ExtraBold.ttf", f"{GOOGLE_FONTS}/tajawal/Tajawal-ExtraBold.ttf"),
        "xbold": ("Tajawal-Black.ttf", f"{GOOGLE_FONTS}/tajawal/Tajawal-Black.ttf"),
        "giant": ("Lalezar-Regular.ttf", f"{GOOGLE_FONTS}/lalezar/Lalezar-Regular.ttf"),
        "script": ("Amiri-Bold.ttf", f"{GOOGLE_FONTS}/amiri/Amiri-Bold.ttf"),
        "mono": ("Tajawal-Black.ttf", f"{GOOGLE_FONTS}/tajawal/Tajawal-Black.ttf"),
    },
    "en": {
        "bold": ("Poppins-Bold.ttf", f"{GOOGLE_FONTS}/poppins/Poppins-Bold.ttf"),
        "xbold": ("Poppins-ExtraBold.ttf", f"{GOOGLE_FONTS}/poppins/Poppins-ExtraBold.ttf"),
        "giant": ("Anton-Regular.ttf", f"{GOOGLE_FONTS}/anton/Anton-Regular.ttf"),
        "script": ("GreatVibes-Regular.ttf", f"{GOOGLE_FONTS}/greatvibes/GreatVibes-Regular.ttf"),
        "mono": ("BebasNeue-Regular.ttf", f"{GOOGLE_FONTS}/bebasneue/BebasNeue-Regular.ttf"),
    },
}
ARABIC_FORMS = ("isol", "init", "medi", "fina")
LAM_ALEF = {0x622: (0xFEF5, 0xFEF6), 0x623: (0xFEF7, 0xFEF8), 0x625: (0xFEF9, 0xFEFA), 0x627: (0xFEFB, 0xFEFC)}

EMOJI_SOURCES = [
    "https://fonts.gstatic.com/s/e/notoemoji/latest/{u}/512.png",
    "https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/72x72/{d}.png",
]

MODES = {"blank", "small", "stack", "giant", "script", "emoji"}
TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
CUE_TIME_RE = re.compile(rf"{TIME}\s*-->\s*{TIME}")
MARK_RE = re.compile(r"<((?:\d+:)?\d{1,2}:\d{2}[,.]\d{1,3})>")
DIR_MARKS_RE = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
ARABIC_RE = re.compile("[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
HOLD_GAP = 0.6

_PICTO = (
    "\u00A9\u00AE\u203C\u2049\u2122\u2139\u2194-\u2199\u21A9\u21AA\u231A\u231B\u2328\u23CF"
    "\u23E9-\u23F3\u23F8-\u23FA\u24C2\u25AA\u25AB\u25B6\u25C0\u25FB-\u25FE\u2600-\u27BF"
    "\u2934\u2935\u2B05-\u2B07\u2B1B\u2B1C\u2B50\u2B55\u3030\u303D\u3297\u3299"
    "\U0001F000-\U0001F1E5\U0001F200-\U0001FAFF"
)
EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2})"
    "|(?:[#*0-9]\uFE0F?\u20E3)"
    f"|(?:[{_PICTO}]\uFE0F?[\U0001F3FB-\U0001F3FF]?"
    f"(?:\u200D[{_PICTO}]\uFE0F?[\U0001F3FB-\U0001F3FF]?)*)"
)

RESHAPER = arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": True, "support_ligatures": True})


# ---------------------------------------------------------------- helpers

def seconds(h, m, s, ms):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_stamp(stamp):
    return seconds(*re.fullmatch(TIME, stamp.strip()).groups())


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def ease_out_cubic(x):
    return 1 - (1 - x) ** 3


def ease_out_back(x, k=1.7):
    return 1 + (k + 1) * (x - 1) ** 3 + k * (x - 1) ** 2


def is_rtl(text):
    return bool(ARABIC_RE.search(text or ""))


@lru_cache(maxsize=4096)
def shape(text):
    """Join Arabic letters and reorder for right-to-left display (one line)."""
    text = strip_emoji(text) if EMOJI_RE.search(text) else text
    if not is_rtl(text):
        return text
    return get_display(RESHAPER.reshape(text))


def strip_emoji(text):
    return re.sub(r"[ \t]{2,}", " ", EMOJI_RE.sub("", text).replace("\uFE0F", "")).strip()


@lru_cache(maxsize=2048)
def load_font(path, size):
    return ImageFont.truetype(path, max(1, int(round(size))), layout_engine=ImageFont.Layout.BASIC)


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 lyric-video"})
    with urllib.request.urlopen(req, timeout=20) as resp, open(path, "wb") as out:
        out.write(resp.read())


def _gsub_maps(font):
    singles, ligs = {tag: {} for tag in ARABIC_FORMS}, {}
    if "GSUB" not in font:
        return singles, ligs
    table = font["GSUB"].table
    lookups = table.LookupList.Lookup
    for record in table.FeatureList.FeatureRecord:
        tag = record.FeatureTag
        for index in record.Feature.LookupListIndex:
            lookup = lookups[index]
            for sub in lookup.SubTable:
                kind = lookup.LookupType
                if kind == 7:
                    kind, sub = sub.ExtensionLookupType, sub.ExtSubTable
                if kind == 1 and tag in singles:
                    for src, dst in sub.mapping.items():
                        singles[tag].setdefault(src, dst)
                elif kind == 4 and tag in ("rlig", "liga", "dlig", "calt", "ccmp"):
                    for first, items in sub.ligatures.items():
                        for lig in items:
                            ligs.setdefault((first, *lig.Component), lig.LigGlyph)
    return singles, ligs


def patch_arabic_font(src, dst):
    """Map Arabic presentation-form code points to the font's own contextual glyphs.

    Pillow without libraqm (the usual Windows install) draws pre-shaped text, which uses
    presentation-form code points many modern Arabic fonts only reach through OpenType GSUB.
    """
    from fontTools.ttLib import TTFont
    from arabic_reshaper.letters import LETTERS_ARABIC

    font = TTFont(src)
    cmap = font.getBestCmap()
    singles, ligs = _gsub_maps(font)
    added = {}
    for base, forms in LETTERS_ARABIC.items():
        glyph = cmap.get(ord(base))
        if glyph is None:
            continue
        for tag, pres in zip(ARABIC_FORMS, forms):
            if pres and len(pres) == 1 and ord(pres) not in cmap:
                added[ord(pres)] = singles[tag].get(glyph, glyph)
    lam = cmap.get(0x644)
    if lam:
        lam_init, lam_medi = singles["init"].get(lam, lam), singles["medi"].get(lam, lam)
        for alef_cp, (iso_cp, fin_cp) in LAM_ALEF.items():
            alef = cmap.get(alef_cp)
            if not alef:
                continue
            alef_fina = singles["fina"].get(alef, alef)
            for cp, first in ((iso_cp, lam_init), (fin_cp, lam_medi)):
                if cp in cmap:
                    continue
                lig = ligs.get((first, alef_fina)) or ligs.get((lam, alef))
                if lig:
                    added[cp] = lig
    for sub in font["cmap"].tables:
        if sub.isUnicode():
            for cp, glyph in added.items():
                if sub.format != 4 or cp <= 0xFFFF:
                    sub.cmap.setdefault(cp, glyph)
    font.save(dst)


def ensure_fonts(folder, lang="ar"):
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, (name, url) in FONT_SETS[lang].items():
        path = folder / name
        if not path.exists():
            print(f"Downloading font {name} ...")
            download(url, path)
        if lang != "ar":
            paths[key] = str(path)
            continue
        patched = folder / f"shaped-{name}"
        if not patched.exists():
            try:
                patch_arabic_font(path, patched)
            except Exception as exc:
                print(f"[!] could not prepare {name} for Arabic ({exc}), using it as is")
                patched = path
        paths[key] = str(patched)
    return paths


class EmojiStore:
    """Downloads emoji PNGs once (Noto 512px, Twemoji fallback) and caches resized copies."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._base, self._sized = {}, {}

    def base(self, emoji):
        if emoji in self._base:
            return self._base[emoji]
        codes = [f"{ord(c):x}" for c in emoji]
        plain = [c for c in codes if c != "fe0f"]
        name = "_".join(plain) or "_".join(codes)
        path = self.folder / f"{name}.png"
        if not path.exists():
            tries = []
            for variant in ("_".join(codes), "_".join(plain)):
                tries.append(EMOJI_SOURCES[0].format(u=variant))
            tries.append(EMOJI_SOURCES[1].format(d="-".join(plain)))
            tries.append(EMOJI_SOURCES[1].format(d="-".join(codes)))
            for url in dict.fromkeys(tries):
                try:
                    download(url, path)
                    Image.open(path).verify()
                    break
                except Exception:
                    path.unlink(missing_ok=True)
        img = None
        if path.exists():
            try:
                img = Image.open(path).convert("RGBA")
            except Exception:
                img = None
        if img is None:
            img = self.from_color_font(emoji)
            if img is not None:
                img.save(path)
        if img is None:
            print(f"[!] emoji {emoji!r} could not be downloaded, skipping it")
        self._base[emoji] = img
        return img

    COLOR_FONTS = [
        (r"C:\Windows\Fonts\seguiemj.ttf", 160),
        ("/System/Library/Fonts/Apple Color Emoji.ttc", 160),
        ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109),
        ("/usr/share/fonts/noto/NotoColorEmoji.ttf", 109),
    ]

    def from_color_font(self, emoji):
        """Offline fallback: draw the emoji in its own colors with the system color-emoji font."""
        for path, size in self.COLOR_FONTS:
            if not os.path.exists(path):
                continue
            try:
                font = ImageFont.truetype(path, size)
                canvas = Image.new("RGBA", (size * 3, size * 3), (0, 0, 0, 0))
                ImageDraw.Draw(canvas).text((size * 1.5, size * 1.5), emoji, font=font,
                                            anchor="mm", embedded_color=True)
                box = canvas.getbbox()
                if not box:
                    continue
                pic = canvas.crop(box)
                side = max(pic.size)
                square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
                square.paste(pic, ((side - pic.width) // 2, (side - pic.height) // 2))
                return square.resize((512, 512), Image.LANCZOS)
            except Exception:
                continue
        return None

    @staticmethod
    def tinted(img, color):
        """Recolor the emoji in the lyric color, keeping its shape and a little shading."""
        color = ImageColor.getrgb(color) if isinstance(color, str) else tuple(color[:3])
        shade = img.convert("L").point(lambda v: 150 + v * 105 // 255)
        layers = [Image.new("L", img.size, c) for c in color]
        rgb = Image.merge("RGB", [ImageChops.multiply(layer, shade) for layer in layers])
        out = rgb.convert("RGBA")
        out.putalpha(img.getchannel("A"))
        return out

    def get(self, emoji, size, alpha=1.0, tint=None):
        size = max(4, int(size) // 4 * 4)
        a = round(clamp(alpha), 1)
        key = (emoji, size, a, tint if tint is None else tuple(tint) if not isinstance(tint, str) else tint)
        if key not in self._sized:
            base = self.base(emoji)
            if base is None:
                self._sized[key] = None
            else:
                img = base.resize((size, size), Image.LANCZOS)
                if tint is not None:
                    img = self.tinted(img, tint)
                if a < 1:
                    img.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
                if len(self._sized) > 3000:
                    self._sized.clear()
                self._sized[key] = img
        return self._sized[key]


DEFAULT_FFMPEG_DIR = r"D:\2 - Programmes\FFmpeg\FFmpeg\bin"


def find_ffmpeg(explicit):
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for candidate in filter(None, [explicit, os.environ.get("FFMPEG_DIR"), DEFAULT_FFMPEG_DIR]):
        path = Path(candidate)
        if path.is_dir():
            path = path / exe
        if path.is_file():
            return str(path)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit("ffmpeg not found. Install it (https://ffmpeg.org) or pass --ffmpeg /path/to/ffmpeg")


def probe_duration(ffmpeg, path):
    info = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stderr
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    if not match:
        return None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


# ---------------------------------------------------------------- SRT -> scenes

@dataclass
class Scene:
    start: float
    end: float
    mode: str
    dark: bool
    steps: list = field(default_factory=list)   # [(time, logical text)]
    emojis: list = field(default_factory=list)  # [(time, emoji)]
    ghost: str | None = None
    rtl: bool = True
    particles: bool = True
    words: list = field(default_factory=list)   # [(time, word)] for the mono template


def read_cues(path):
    raw = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    raw = DIR_MARKS_RE.sub("", raw)
    cues = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            match = CUE_TIME_RE.search(line)
            if match:
                g = match.groups()
                cues.append((seconds(*g[:4]), seconds(*g[4:]), "\n".join(lines[i + 1:]).strip()))
                break
    return sorted(cues, key=lambda c: c[0])


def auto_mode(text):
    if not text:
        return "blank"
    if re.fullmatch(r"\*.+\*", text, re.S):
        return "script"
    if "\n" in text:
        return "stack"
    words = text.split()
    if is_rtl(text):
        if len(words) == 1 and text.endswith("!") and len(text) >= 3:
            return "giant"
        return "small"
    if len(words) == 1 and text.isupper() and len(text) >= 3:
        return "giant"
    if len(words) > 1 and text.isupper():
        return "stack"
    return "small"


def split_units(mode, body):
    parts = MARK_RE.split(body)
    segments = [(parts[0], None)] + [(parts[i + 1], parse_stamp(parts[i])) for i in range(1, len(parts), 2)]
    units = []
    for text, stamp in segments:
        if mode == "stack":
            pieces = [line.strip() for line in text.split("\n")]
        else:
            pieces = text.split()
        pieces = [p for p in pieces if p]
        for i, piece in enumerate(pieces):
            units.append([piece, stamp if i == 0 else None])
    return units


def fill_times(units, start, end):
    if units[0][1] is None:
        units[0][1] = start
    i, n = 1, len(units)
    while i < n:
        if units[i][1] is not None:
            i += 1
            continue
        j = i
        while j < n and units[j][1] is None:
            j += 1
        a, gap = units[i - 1][1], j - i
        b = units[j][1] if j < n else min(end - 0.05, a + 0.3 * (gap + 1))
        for k in range(i, j):
            units[k][1] = a + (b - a) * (k - i + 1) / (gap + 1)
        i = j
    for unit in units:
        unit[1] = clamp(unit[1], start, max(start, end))


def build_scene(start, end, body, index):
    flags, opts = set(), {}
    while (tag := re.match(r"\s*\{([^}]*)\}", body)):
        body = body[tag.end():]
        for part in tag.group(1).split(","):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                opts[key.strip().lower()] = value.strip()
            else:
                flags.update(p.lower() for p in part.split())
    body = re.sub(r"</?[A-Za-z][^>]*>", "", body).strip()
    plain = MARK_RE.sub("", body).strip()
    text_only = strip_emoji(plain)

    starred = re.fullmatch(r"\*(.+)\*", strip_emoji(body), re.S)
    mode = next((f for f in flags if f in MODES), None) or auto_mode(text_only)
    if starred and mode == "script":
        body = re.sub(r"\*", "", body)
        plain = MARK_RE.sub("", body).strip()
        text_only = strip_emoji(plain)
    dark = "dark" in flags or ("light" not in flags and index % 2 == 1)
    scene = Scene(start, end, mode, dark, rtl=is_rtl(text_only) or not text_only)
    scene.particles = "noemoji" not in flags

    if not plain or mode == "blank":
        scene.mode = "blank"
        return scene

    if mode == "script":
        units = split_units("small", body)
        fill_times(units, start, end)
        for text, stamp in units:
            for e in EMOJI_RE.findall(text):
                scene.emojis.append((stamp, e))
        if text_only:
            scene.steps = [(start, re.sub(r"\s+", " ", text_only))]
            scene.words = [(stamp, strip_emoji(text)) for text, stamp in units if strip_emoji(text).strip()]
        else:
            scene.mode = "emoji"
    else:
        units = split_units(mode, body)
        if mode == "stack" and len(units) == 1 and "\n" not in plain and " " in plain:
            units = [[w, units[0][1] if k == 0 else None] for k, w in enumerate(plain.split())]
        fill_times(units, start, end)
        clean = []
        for text, stamp in units:
            for e in EMOJI_RE.findall(text):
                scene.emojis.append((stamp, e))
            text = strip_emoji(text)
            if text:
                clean.append((stamp, text))
        if not clean:
            scene.mode = "emoji" if scene.emojis else "blank"
            return scene
        for stamp, text in clean:
            for k, word in enumerate(text.split()):
                scene.words.append((stamp + 0.06 * k, word))
        if mode == "giant":
            word = "".join(t for _, t in clean).rstrip("!")
            chunks = 2 if len(word) <= 4 else 3
            g = [[word, clean[0][0]]] + [[word, None] for _ in range(chunks - 1)]
            fill_times(g, start, end)
            scene.steps = [(s, w) for w, s in g]
        else:
            acc = []
            for stamp, text in clean:
                acc.append(text)
                scene.steps.append((stamp, " ".join(acc) if mode == "small" else text))

    if "noghost" in flags:
        scene.ghost = None
    elif opts.get("ghost"):
        scene.ghost = opts["ghost"]
    elif scene.mode == "stack":
        scene.ghost = scene.steps[-1][1]
    elif scene.mode == "giant":
        scene.ghost = scene.steps[-1][1]
    return scene


def build_timeline(cues, duration):
    scenes = [build_scene(s, e, body, i) for i, (s, e, body) in enumerate(cues)]
    if not scenes:
        return [Scene(0, duration, "blank", False)]
    timeline = []
    if scenes[0].start > 0:
        timeline.append(Scene(0, scenes[0].start, "blank", scenes[0].dark))
    for i, scene in enumerate(scenes):
        nxt = scenes[i + 1].start if i + 1 < len(scenes) else duration
        scene.end = min(scene.end, nxt)
        timeline.append(scene)
        if nxt - scene.end <= HOLD_GAP:
            scene.end = nxt
        else:
            timeline.append(Scene(scene.end, nxt, "blank", scene.dark))
    return timeline


# ---------------------------------------------------------------- drawing

def active_step(steps, t):
    k = -1
    for i, (stamp, _) in enumerate(steps):
        if stamp <= t:
            k = i
        else:
            break
    return k


class Renderer:
    def __init__(self, width, height, fonts, light, dark, emojis):
        self.W, self.H = width, height
        self.U = min(width, height)
        self.u = self.U / 1080
        self.portrait = height > width
        self.fonts = fonts
        self.light, self.dark = light, dark
        self.emoji = emojis
        self.original_emoji = False
        self.emoji_tint = None
        self.ghost_room = int(60 * self.u * 8)
        self._ghost, self._giant, self._script, self._wrap = {}, {}, {}, {}
        self.cy = height / 2
        self.scale = 1.0

    def font(self, key, size):
        return load_font(self.fonts[key], size)

    def fit(self, key, texts, size, max_w):
        widest = max((self.font(key, size).getlength(shape(t)) for t in texts), default=0)
        return size * max_w / widest if widest > max_w else size

    def shake(self, t, stamp):
        decay = clamp(1 - (t - stamp) / 0.12)
        amp = self.U * 0.01 * decay
        return amp * math.sin((t - stamp) * 95 + stamp * 7), amp * math.cos((t - stamp) * 80 + stamp * 3)

    def frame(self, scene, t):
        bg, fg = (self.dark, self.light) if scene.dark else (self.light, self.dark)
        img = Image.new("RGB", (self.W, self.H), bg)
        self.emoji_tint = None if self.original_emoji else fg
        has_emoji = bool(scene.emojis) and scene.mode != "emoji"
        if has_emoji:
            self.cy = self.H * (0.6 if self.portrait else 0.62)
            self.scale = 0.82
        else:
            self.cy, self.scale = self.H / 2, 1.0
        if scene.ghost:
            self.draw_ghost(img, scene, t, fg)
        if scene.emojis and scene.particles:
            self.draw_particles(img, scene, t)
        getattr(self, f"draw_{scene.mode}")(img, scene, t, fg)
        if scene.emojis:
            self.draw_main_emojis(img, scene, t)
        return img

    def draw_blank(self, img, scene, t, fg):
        pass

    def draw_emoji(self, img, scene, t, fg):
        pass

    # --- words building up one by one (wraps to 2 lines when long)
    def small_layout(self, scene):
        key = id(scene)
        if key not in self._wrap:
            full = scene.steps[-1][1]
            words = full.split()
            base = self.U * (0.16 if self.portrait else 0.17) * self.scale
            one = self.fit("bold", [full], base, self.W * 0.84)
            split = None
            if one < base * 0.62 and len(words) >= 3:
                split = math.ceil(len(words) / 2)
                lines = [" ".join(words[:split]), " ".join(words[split:])]
                one = self.fit("bold", lines, base, self.W * 0.86)
            self._wrap[key] = (one, split)
        return self._wrap[key]

    def draw_small(self, img, scene, t, fg):
        k = active_step(scene.steps, t)
        if k < 0:
            return
        stamp, text = scene.steps[k]
        base, split = self.small_layout(scene)
        size = base * (0.8 + 0.2 * ease_out_back(clamp((t - stamp) / 0.16)))
        dx, dy = self.shake(t, stamp)
        font = self.font("bold", size)
        draw = ImageDraw.Draw(img)
        if split is None:
            draw.text((self.W / 2 + dx, self.cy + dy), shape(text), font=font, fill=fg, anchor="mm")
            return
        words, lh = text.split(), base * 1.15
        lines = [" ".join(words[:split]), " ".join(words[split:])]
        for i, line in enumerate(lines):
            if line:
                y = self.cy + (i - 0.5) * lh + dy
                draw.text((self.W / 2 + dx, y), shape(line), font=font, fill=fg, anchor="mm")

    # --- big bold lines sliding in
    def draw_stack(self, img, scene, t, fg):
        k = active_step(scene.steps, t)
        if k < 0:
            return
        steps = scene.steps
        base = self.U * (0.2 if self.portrait else 0.22) * self.scale
        size = self.fit("xbold", [s for _, s in steps], base, self.W * 0.88)
        size = min(size, (self.H * (0.55 if scene.emojis else 0.8)) / max(1, len(steps)) / 1.05)
        font = self.font("xbold", size)
        lh = size * 1.1
        top = self.cy - (len(steps) - 1) * lh / 2
        dx, dy = self.shake(t, steps[k][0])
        mask = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(mask)
        side = 1 if scene.rtl else -1
        for i, (stamp, line) in enumerate(steps[: k + 1]):
            p = ease_out_cubic(clamp((t - stamp) / 0.22))
            y = top + i * lh + (1 - p) * lh * 0.45
            x = self.W / 2 + side * (1 - p) * self.U * 0.08
            draw.text((x + dx, y + dy), shape(line), font=font, fill=int(255 * min(1, p * 1.5)), anchor="mm")
        img.paste(fg, (0, 0), mask)

    # --- one giant stretched word, revealed in chunks (right-to-left for Arabic)
    def giant_full(self, word, tw, th):
        key = (word, int(tw), int(th))
        if key not in self._giant:
            font = self.font("giant", th * 1.2)
            shown = shape(word)
            left, top, right, bottom = font.getbbox(shown)
            full = Image.new("L", (max(1, right - left), max(1, bottom - top)), 0)
            ImageDraw.Draw(full).text((-left, -top), shown, font=font, fill=255)
            self._giant[key] = full.resize((max(1, round(tw)), max(1, round(th))), Image.LANCZOS)
        return self._giant[key]

    def draw_giant(self, img, scene, t, fg):
        k = active_step(scene.steps, t)
        if k < 0:
            return
        stamp, word = scene.steps[k]
        n = len(scene.steps)
        tw = self.W * 0.9
        th = min(self.H * (0.5 if scene.emojis else 0.72), self.U * (0.85 if scene.emojis else 1.2))
        full = self.giant_full(word, tw, th)
        cut = max(1, int(full.width * (k + 1) / n))
        if scene.rtl:
            part, shift = full.crop((full.width - cut, 0, full.width, full.height)), full.width - cut
        else:
            part, shift = full.crop((0, 0, cut, full.height)), 0
        x0, y0 = (self.W - tw) / 2 + shift, self.cy - th / 2
        punch = 1 + 0.07 * (1 - ease_out_cubic(clamp((t - stamp) / 0.14)))
        dx, dy = self.shake(t, stamp)
        if punch > 1.001:
            part = part.resize((max(1, int(part.width * punch)), max(1, int(part.height * punch))), Image.BILINEAR)
            cx, cy = self.W / 2, self.cy
            x0, y0 = cx + (x0 - cx) * punch, cy + (y0 - cy) * punch
        img.paste(fg, (int(x0 + dx), int(y0 + dy)), part)

    # --- calligraphy word that writes itself (from the right for Arabic)
    def script_layer(self, text, scale):
        key = (text, scale)
        if key not in self._script:
            size = self.fit("script", [text], self.U * (0.42 if self.portrait else 0.36) * scale, self.W * 0.86)
            mask = Image.new("L", (self.W, self.H), 0)
            ImageDraw.Draw(mask).text((self.W / 2, self.cy), shape(text), font=self.font("script", size),
                                      fill=255, anchor="mm")
            self._script[key] = (mask, mask.getbbox() or (0, 0, 1, 1))
        return self._script[key]

    def draw_script(self, img, scene, t, fg):
        stamp, text = scene.steps[0]
        if t < stamp:
            return
        mask, (left, top, right, bottom) = self.script_layer(text, self.scale)
        p = ease_out_cubic(clamp((t - stamp) / 0.8))
        width = int((right - left) * p)
        if width <= 0:
            return
        offset = int((1 - p) * self.U * 0.04)
        if scene.rtl:
            box = (right - width, top, right, bottom)
            img.paste(fg, (right - width, top + offset), mask.crop(box))
        else:
            img.paste(fg, (left, top + offset), mask.crop((left, top, left + width, bottom)))

    # --- outlined text drifting behind
    def ghost_mask(self, text):
        if text not in self._ghost:
            size = self.U * 0.6
            font = self.font("giant", size)
            side = int(math.hypot(self.W, self.H) + 2 * self.ghost_room + size)
            unit = shape(text) + "   "
            row = unit * (int(side / max(1.0, font.getlength(unit))) + 3)
            stroke = max(2, round(4 * self.u))
            outer, inner = Image.new("L", (side, side), 0), Image.new("L", (side, side), 0)
            draw_outer, draw_inner = ImageDraw.Draw(outer), ImageDraw.Draw(inner)
            rows = int(side / size / 2) + 2
            for r in range(-rows, rows + 1):
                pos = (side / 2 + r * 40 * self.u, side / 2 + r * size)
                draw_outer.text(pos, row, font=font, fill=255, anchor="mm", stroke_width=stroke, stroke_fill=255)
                draw_inner.text(pos, row, font=font, fill=255, anchor="mm")
            outline = ImageChops.subtract(outer, inner).point(lambda v: v * 36 // 255)
            self._ghost[text] = outline.rotate(math.degrees(-0.32), resample=Image.BICUBIC)
        return self._ghost[text]

    def draw_ghost(self, img, scene, t, fg):
        mask = self.ghost_mask(scene.ghost)
        center = mask.width / 2
        drift = min(self.ghost_room, max(0.0, t - scene.start) * 60 * self.u)
        if scene.rtl:
            left = int(center - self.W / 2 + self.ghost_room / 2 - drift)
        else:
            left = int(center - self.W / 2 - self.ghost_room / 2 + drift)
        top = int(center - self.H / 2)
        img.paste(fg, (0, 0), mask.crop((left, top, left + self.W, top + self.H)))

    # --- emoji
    def paste_emoji(self, img, emoji, cx, cy, size, angle=0.0, alpha=1.0):
        pic = self.emoji.get(emoji, size, alpha, getattr(self, "emoji_tint", None))
        if pic is None:
            return
        if abs(angle) > 0.5:
            pic = pic.rotate(angle, resample=Image.BICUBIC, expand=True)
        img.paste(pic, (int(cx - pic.width / 2), int(cy - pic.height / 2)), pic)

    def draw_particles(self, img, scene, t):
        shown = [(s, e) for s, e in scene.emojis if s <= t]
        if not shown:
            return
        seen = []
        for s, e in shown:
            if e not in seen:
                seen.append(e)
        per = 7 if len(seen) == 1 else 5 if len(seen) == 2 else 4
        first = {e: min(s for s, x in shown if x == e) for e in seen}
        for e in seen[:4]:
            age0 = t - first[e]
            for j in range(per):
                rnd = random.Random(f"{scene.start:.3f}|{e}|{j}")
                size = self.U * rnd.uniform(0.06, 0.12)
                speed = self.U * rnd.uniform(0.14, 0.3)
                travel = self.H + size * 2
                y0 = rnd.uniform(0.2, 1.0) * travel
                age = age0 - rnd.uniform(0, 0.5)
                if age <= 0:
                    continue
                y = self.H + size - ((y0 + age * speed) % travel)
                phase = rnd.uniform(0, math.tau)
                x = rnd.uniform(0.06, 0.94) * self.W + math.sin(t * rnd.uniform(1.0, 2.0) + phase) * self.U * 0.04
                angle = math.sin(t * rnd.uniform(1.5, 2.8) + phase) * 22
                fade = clamp(age / 0.4)
                self.paste_emoji(img, e, x, y, size, angle, 0.55 * fade)

    def draw_main_emojis(self, img, scene, t):
        shown = [(s, e) for s, e in scene.emojis if s <= t]
        if not shown:
            return
        shown = shown[-4:]
        n = len(shown)
        if scene.mode == "emoji":
            base = self.U * (0.5 if n == 1 else 0.36 if n == 2 else 0.27)
            row_y = self.H / 2
        else:
            base = self.U * (0.2 if self.portrait else 0.19) * (1 if n <= 2 else 0.85)
            row_y = self.H * (0.3 if self.portrait else 0.25)
        gap = base * 1.15
        x_first = self.W / 2 + (n - 1) * gap / 2 if scene.rtl else self.W / 2 - (n - 1) * gap / 2
        step = -gap if scene.rtl else gap
        for i, (s, e) in enumerate(shown):
            age = t - s
            pop = ease_out_back(clamp(age / 0.42), k=2.6)
            pulse = 1 + 0.06 * math.sin(age * 7.5 + i)
            size = base * max(0.05, pop) * pulse
            bob = math.sin(age * 3.3 + i * 1.7) * self.U * 0.022
            sway = math.sin(age * 2.1 + i) * self.U * 0.012
            angle = (1 - clamp(age / 0.42)) * -35 + math.sin(age * 2.7 + i) * 10
            self.paste_emoji(img, e, x_first + i * step + sway, row_y + bob, size, angle)


class MonoRenderer(Renderer):
    """Pure black / white template with After Effects style word animation:
    each word pops in (scale overshoot), sharpens from a motion blur and slides into place,
    the whole line slowly pushes in like a camera, and every new line cuts in with a flash."""

    BLACK, WHITE = (0, 0, 0), (255, 255, 255)
    POP = 0.28          # seconds for a word to land
    COLUMN = 0.36

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._mono = {}
        self._words = {}

    def emphasized(self, scene):
        last = scene.words[-1][1] if scene.words else ""
        return scene.mode == "giant" or last.endswith("!") or (not scene.rtl and last.isupper() and len(last) > 2)

    def mono_layout(self, scene):
        key = (id(scene), self.cy)
        if key in self._mono:
            return self._mono[key]
        big = self.emphasized(scene)
        size = int(self.H * (0.27 if big else 0.17) * self.scale)
        max_w = self.W * self.COLUMN * (1.35 if big else 1.0)
        words = [(st, shape(w) if scene.rtl else w.upper()) for st, w in scene.words]
        widest = max(self.font("mono", size).getlength(w) for _, w in words)
        if widest > self.W * 0.82:
            size = int(size * self.W * 0.82 / widest)
        font = self.font("mono", size)
        space = font.getlength(" ")
        lines, line, width = [], [], 0.0
        for stamp, word in words:
            w = font.getlength(word)
            if line and width + space + w > max_w:
                lines.append((line, width))
                line, width = [], 0.0
            line.append((stamp, word, w))
            width += (space if len(line) > 1 else 0) + w
        lines.append((line, width))
        lh = size * 0.98
        top = self.cy - lh * len(lines) / 2 + lh / 2
        placed = []
        for row, (line, lw) in enumerate(lines):
            y = top + row * lh
            if scene.rtl:
                x = self.W / 2 + lw / 2
                for stamp, word, w in line:
                    placed.append((stamp, word, x - w / 2, y, w))
                    x -= w + space
            else:
                x = self.W / 2 - lw / 2
                for stamp, word, w in line:
                    placed.append((stamp, word, x + w / 2, y, w))
                    x += w + space
        self._mono[key] = (font, placed)
        return font, placed

    def word_mask(self, font, word):
        key = (id(font), word)
        if key not in self._words:
            l, t, r, b = font.getbbox(word, anchor="mm")
            pad = int(font.size * 0.4)
            im = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad), 0)
            ImageDraw.Draw(im).text((im.width / 2, im.height / 2), word, font=font, fill=255, anchor="mm")
            self._words[key] = im
        return self._words[key]

    def text_mask(self, scene, t):
        font, placed = self.mono_layout(scene)
        mask = Image.new("L", (self.W, self.H), 0)
        entry = 1 if scene.rtl else -1
        life = t - scene.start
        push = 1.0 + 0.05 * ease_out_cubic(clamp(life / max(0.4, scene.end - scene.start)))
        cx, cy = self.W / 2, self.cy
        for stamp, word, x, y, w in placed:
            age = t - stamp
            if age < 0:
                continue
            p = clamp(age / self.POP)
            sc = (0.55 + 0.45 * ease_out_back(p, 2.2)) * push
            blur = (1 - ease_out_cubic(p)) * font.size * 0.22
            dx = entry * (1 - ease_out_cubic(p)) * font.size * 0.9
            alpha = clamp(age / 0.06)
            src = self.word_mask(font, word)
            if abs(sc - 1) > 0.002:
                src = src.resize((max(1, int(src.width * sc)), max(1, int(src.height * sc))), Image.BILINEAR)
            if blur > 0.6:
                src = src.filter(ImageFilter.BoxBlur(blur))
            if alpha < 1:
                src = src.point(lambda v, a=alpha: int(v * a))
            px = cx + (x - cx) * push + dx
            py = cy + (y - cy) * push
            box = (int(px - src.width / 2), int(py - src.height / 2))
            layer = Image.new("L", mask.size, 0)
            layer.paste(src, box)
            mask = ImageChops.lighter(mask, layer)
        return mask

    def frame(self, scene, t):
        dark = scene.dark
        bg, ink = (self.BLACK, self.WHITE) if dark else (self.WHITE, self.BLACK)
        img = Image.new("RGB", (self.W, self.H), bg)
        self.emoji_tint = None if self.original_emoji else ink
        has_emoji = bool(scene.emojis) and scene.mode != "emoji"
        self.cy, self.scale = (self.H * 0.62, 0.85) if has_emoji else (self.H / 2, 1.0)
        if scene.emojis and scene.particles:
            self.draw_particles(img, scene, t)
        if scene.words and scene.mode not in ("blank", "emoji"):
            mask = self.text_mask(scene, t).point(lambda v: 255 if v > 127 else int(v * 2))
            img.paste(ink, mask=mask)
        if scene.emojis:
            self.draw_main_emojis(img, scene, t)
        if t - scene.start < 0.034:
            img = ImageChops.invert(img)
        return img

    def paste_emoji(self, img, e, x, y, size, angle, alpha=1.0):
        super().paste_emoji(img, e, x, y, size, angle, 1.0 if alpha > 0.25 else 0.0)


# ---------------------------------------------------------------- encode

def ffmpeg_command(ffmpeg, args, duration):
    w, h, fps = args.width, args.height, args.fps
    bitrate = args.bitrate or ("20M" if fps > 30 else "12M")
    mbps = float(re.sub(r"[^0-9.]", "", bitrate))
    level = "4.2" if w * h <= 1920 * 1088 else "5.1" if w * h * fps <= 2560 * 1440 * 60 else "5.2"
    audio_in = ["-i", args.audio] if args.audio else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
        *audio_in,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
        "-c:v", "libx264", "-preset", args.preset, "-profile:v", "high", "-level:v", level,
        "-b:v", bitrate, "-minrate", bitrate, "-maxrate", bitrate, "-bufsize", f"{mbps * 2:g}M",
        "-x264-params", "nal-hrd=cbr:force-cfr=1",
        "-g", str(fps), "-bf", "2", "-r", str(fps),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-c:a", "aac", "-b:a", args.audio_bitrate, "-ar", "48000", "-ac", "2",
        "-t", f"{duration:.3f}", "-movflags", "+faststart",
        args.out,
    ]


# Always 16:9. quality: (width, height, bitrate)
QUALITIES = {
    "720p": (1280, 720, "10M"),
    "fhd": (1920, 1080, "20M"),
    "2k": (2560, 1440, "40M"),
    "4k": (3840, 2160, "60M"),
}

# name: (label, dark background/text, light background/text)
PALETTES = {
    "gold":    ("Night + desert gold",             "#14100A", "#E9C46A"),
    "emerald": ("Emerald + cream",                 "#0B3B2E", "#F1E6C8"),
    "sand":    ("Coffee + sand",                   "#2B1A10", "#E8D3B0"),
    "indigo":  ("Indigo night + rose gold",        "#16133A", "#F0C2A8"),
    "wine":    ("Wine + soft pink",                "#3E0B2C", "#D8B4CA"),
    "maroon":  ("Maroon + taupe",                  "#390001", "#B19886"),
    "crimson": ("Bright crimson + cream",          "#9E0B1F", "#FBE9DD"),
    "navy":    ("Navy + ice blue",                 "#0B1B3F", "#B9CDF0"),
    "teal":    ("Deep teal + mint",                "#06302F", "#B5E3D6"),
    "purple":  ("Purple + lavender",               "#2B0F4C", "#D6C6F2"),
    "noir":    ("Black + cream",                   "#0E0E0E", "#EEE6D3"),
    "lime":    ("Navy + lime",                     "#0B1B3F", "#E3FF73"),
}
DEFAULT_PALETTE = "gold"


def ask_palette():
    names = list(PALETTES)
    print("\nChoose colors:")
    for i, name in enumerate(names, 1):
        label, dark, light = PALETTES[name]
        print(f"  {i:>2} = {label:<32} {dark} / {light}")
    print(f"  {len(names) + 1:>2} = Custom (type your own hex codes)")
    while True:
        answer = input(f"Choose 1-{len(names) + 1} [1]: ").strip() or "1"
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1], None, None
        if answer == str(len(names) + 1):
            dark = input("  Dark color hex (e.g. #14100A): ").strip()
            light = input("  Light color hex (e.g. #E9C46A): ").strip()
            try:
                ImageColor.getrgb(dark), ImageColor.getrgb(light)
                return "custom", dark, light
            except ValueError:
                print("  Not a valid color, try again.")
                continue
        print("  Please type a number from the list.")


def resolve_colors(args):
    if args.palette is None and not (args.dark and args.light) and sys.stdin and sys.stdin.isatty():
        args.palette, dark, light = ask_palette()
        args.dark, args.light = args.dark or dark, args.light or light
    name = args.palette or DEFAULT_PALETTE
    if name != "custom":
        _, dark, light = PALETTES[name]
        args.dark, args.light = args.dark or dark, args.light or light
    elif not (args.dark and args.light):
        sys.exit('--palette custom needs --dark "#hex" and --light "#hex"')
    args.palette = name
    try:
        ImageColor.getrgb(args.dark), ImageColor.getrgb(args.light)
    except ValueError as err:
        sys.exit(f"Bad color: {err}")
    print(f"[ok] colors: {name}  dark {args.dark}  light {args.light}")


def pick_files(args):
    """Open file dialogs when no --srt is given (song first, lyrics auto-matched)."""
    if args.srt:
        return
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if not args.audio:
        args.audio = filedialog.askopenfilename(
            title="1/2  Choose the song (MP3 or MP4)",
            filetypes=[("Audio or video (MP3, MP4)", "*.mp3 *.mp4"), ("MP3 audio", "*.mp3"), ("MP4 video", "*.mp4")],
        ) or None
        if not args.audio:
            sys.exit("No song chosen.")
    song = Path(args.audio)
    match = next((p for p in song.parent.glob("*.srt") if p.stem.lower() == song.stem.lower()), None)
    if not match:
        match = next((p for p in song.parent.glob("*.srt") if p.stem.lower().startswith(song.stem.lower())), None)
    if match:
        args.srt = str(match)
        print(f"[ok] lyrics auto-selected: {match.name}")
    if not args.srt:
        args.srt = filedialog.askopenfilename(
            title="2/2  Choose the lyrics (SRT)",
            initialdir=str(song.parent),
            filetypes=[("SRT subtitles", "*.srt")],
        ) or None
        if not args.srt:
            sys.exit("No SRT chosen.")
    root.destroy()


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Arabic / English SRT -> lyric video with animated emoji.")
    parser.add_argument("--lang", choices=["ar", "en"], default="ar", help="ar = Arabic, en = English")
    parser.add_argument("--style", choices=["mono", "classic"], default="mono",
                        help="mono = black/white flashing (new), classic = colored kinetic style")
    parser.add_argument("--srt", help="lyrics subtitle file (.srt); a file picker opens if omitted")
    parser.add_argument("--audio", help="song file (.mp3 or .mp4, its audio is used); sets the video length")
    parser.add_argument("--out", help="output .MKV (default: <song name>-<palette>-<format>-<size>-<fps>fps.MKV)")
    parser.add_argument("--width", type=int, help="override width")
    parser.add_argument("--height", type=int, help="override height")
    parser.add_argument("--quality", choices=list(QUALITIES), default="fhd",
                        help="720p (10M), fhd = 1080p (20M), 2k = 1440p (40M), 4k = 2160p (60M)")
    parser.add_argument("--fps", type=int, default=60, help="30 or 60 (default 60)")
    parser.add_argument("--original-emoji", action="store_true",
                        help="keep emoji in their own colors (default: same color as the lyrics)")
    parser.add_argument("--palette", choices=list(PALETTES) + ["custom"],
                        help="color set (a menu opens if omitted): " + ", ".join(PALETTES))
    parser.add_argument("--light", help="light color hex, overrides the palette")
    parser.add_argument("--dark", help="dark color hex, overrides the palette")
    parser.add_argument("--bitrate", help="constant video bitrate (default set by --quality)")
    parser.add_argument("--audio-bitrate", default="256k")
    parser.add_argument("--preset", default="slow", help="x264 preset (slow = best quality)")
    parser.add_argument("--duration", type=float, help="force length in seconds")
    parser.add_argument("--fonts", default=str(here / "fonts"), help="folder for the .ttf fonts")
    parser.add_argument("--emoji-dir", default=str(here / "emoji"), help="folder for cached emoji images")
    parser.add_argument("--ffmpeg", help="path to ffmpeg if it is not on PATH")
    parser.add_argument("--preview", action="store_true", help="fast half-size test render")
    parser.add_argument("--still", type=float, action="append",
                        help="save a PNG of the frame at this second instead of rendering (repeatable)")
    args = parser.parse_args()

    pick_files(args)
    if args.style == "mono":
        args.palette, args.dark, args.light = "mono", "#000000", "#FFFFFF"
        print("[ok] template: mono (black / white)")
    else:
        resolve_colors(args)
    default_w, default_h, quality_bitrate = QUALITIES[args.quality]
    args.bitrate = args.bitrate or quality_bitrate
    args.width = args.width or default_w
    args.height = args.height or default_h
    if args.preview:
        args.width, args.height, args.preset = args.width // 2, args.height // 2, "veryfast"
    if args.fps not in (30, 60):
        sys.exit("--fps must be 30 or 60")
    base = Path(args.audio or args.srt)
    kind = "preview" if args.preview else f"{args.width}x{args.height}-{args.fps}fps"
    args.out = args.out or str(base.with_name(f"{base.stem}-{args.lang}-{args.palette}-{kind}.MKV"))

    fonts = ensure_fonts(Path(args.fonts), args.lang)
    cues = read_cues(args.srt)
    if not cues:
        sys.exit(f"No subtitles found in {args.srt}")
    emojis = EmojiStore(args.emoji_dir)
    ffmpeg = None if args.still else find_ffmpeg(args.ffmpeg)
    duration = args.duration or (probe_duration(ffmpeg, args.audio) if args.audio and ffmpeg else None) \
        or cues[-1][1] + 1
    light, dark = ImageColor.getrgb(args.light), ImageColor.getrgb(args.dark)
    timeline = build_timeline(cues, duration)
    for scene in timeline:
        for _, e in scene.emojis:
            emojis.base(e)
    renderer = MonoRenderer if args.style == "mono" else Renderer
    kinetic = renderer(args.width, args.height, fonts, light, dark, emojis)
    kinetic.original_emoji = args.original_emoji

    def scene_at(t):
        return next((s for s in timeline if s.start <= t < s.end), timeline[-1])

    if args.still:
        for t in args.still:
            path = base.with_name(f"{base.stem}-still-{t:.2f}s.png")
            kinetic.frame(scene_at(t), t).save(path)
            print(f"[ok] still {t:.2f}s -> {path}")
        return

    cursor = [0]

    def frame_at(t):
        while cursor[0] < len(timeline) - 1 and t >= timeline[cursor[0]].end:
            cursor[0] += 1
        return kinetic.frame(timeline[cursor[0]], t)

    total = int(round(duration * args.fps))
    print(f"Rendering {len(cues)} cues, {duration:.2f}s, {args.width}x{args.height} @ {args.fps}fps -> {args.out}")
    proc = subprocess.Popen(ffmpeg_command(ffmpeg, args, duration), stdin=subprocess.PIPE)
    try:
        for f in range(total):
            proc.stdin.write(frame_at(f / args.fps).tobytes())
            if f % args.fps == 0:
                print(f"\r  {f / total:6.1%}", end="", flush=True)
    except BrokenPipeError:
        pass
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg failed (see error above)")
    print(f"\r  100.0%\nRendered: {args.out}")
    final = Path(args.out)
    print(f"\n[+] Finished. Output saved to:\n    {final.resolve()}")
    if os.environ.get("LYRIC_OUT_FILE"):
        Path(os.environ["LYRIC_OUT_FILE"]).write_text(str(final.resolve()), encoding="utf-8")



if __name__ == "__main__":
    main()
