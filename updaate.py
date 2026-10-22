#!/usr/bin/env python3
"""
Kinetic-typography lyric video from an SRT file (Pillow frames -> ffmpeg H.264).

Default output is YouTube 1920x1080 (16:9), H.264 High, 60 fps,
constant 20 Mbps, AAC 256 kbps 48 kHz, faststart. Use --quality 720p for 1280x720.
Picking a song auto-selects the .srt with the same name in that folder.

Usage (Windows): double-click "Make Lyric Video.bat" and pick the MP3 + SRT.

Usage (command line):
    pip install pillow
    python lyric_video.py                                                   # opens file pickers
    python lyric_video.py --srt good-reason.srt --audio good-reason.mp3 --out good-reason.MKV
    python lyric_video.py --srt song.srt --audio song.mp3 --fps 30          # 30 fps, ~12 Mbps
    python lyric_video.py --srt song.srt --audio song.mp3 --preview         # fast low-res test
    python lyric_video.py --srt song.srt --audio song.mp3 --palette royal   # pick a color set
    python lyric_video.py --srt song.srt --dark "#3E0B2C" --light "#D8B4CA" # your own hex codes

Colors: a numbered menu opens when you run it without --palette/--dark/--light.
Sets: wine, maroon, red, crimson, navy, royal, teal, forest, purple, noir, sunset, lime.

Fonts (Anton, Poppins Bold/ExtraBold, Great Vibes) download automatically into ./fonts.

SRT style tags (optional, at the very start of a cue's text):
    {small}   lowercase words that build up one by one        e.g. "if only"
    {stack}   big bold lines that slide in one by one         e.g. "HAD A\\nGOOD\\nREASON"
    {giant}   one word stretched to fill the screen, letters revealed in chunks
    {script}  handwritten word that writes itself on          (or wrap text in *stars*)
    {blank}   empty background
    {dark} / {light}            background color for this cue (default: alternates)
    {ghost=WORD} / {noghost}    outlined text drifting behind the lyrics
Combine with commas: {stack,dark,ghost=REASON}

Inline timing (optional): put <00:00:02,420> before a word, a line, or a group
of letters to set exactly when it appears. Without it, words are spread
automatically across the cue.
"""

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont

GOOGLE_FONTS = "https://raw.githubusercontent.com/google/fonts/main/ofl"
FONTS = {
    "anton": ("Anton-Regular.ttf", f"{GOOGLE_FONTS}/anton/Anton-Regular.ttf"),
    "bold": ("Poppins-Bold.ttf", f"{GOOGLE_FONTS}/poppins/Poppins-Bold.ttf"),
    "xbold": ("Poppins-ExtraBold.ttf", f"{GOOGLE_FONTS}/poppins/Poppins-ExtraBold.ttf"),
    "script": ("GreatVibes-Regular.ttf", f"{GOOGLE_FONTS}/greatvibes/GreatVibes-Regular.ttf"),
}

MODES = {"blank", "small", "stack", "giant", "script"}
TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
CUE_TIME_RE = re.compile(rf"{TIME}\s*-->\s*{TIME}")
MARK_RE = re.compile(r"<((?:\d+:)?\d{1,2}:\d{2}[,.]\d{1,3})>")
HOLD_GAP = 0.6


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


@lru_cache(maxsize=2048)
def load_font(path, size):
    return ImageFont.truetype(path, max(1, int(round(size))))


def ensure_fonts(folder):
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, (name, url) in FONTS.items():
        path = folder / name
        if not path.exists():
            print(f"Downloading font {name} ...")
            urllib.request.urlretrieve(url, path)
        paths[key] = str(path)
    return paths


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
    info = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
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
    steps: list = field(default_factory=list)  # [(time, text)]
    ghost: str | None = None


def read_cues(path):
    raw = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
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
        if mode == "giant":
            pieces = [re.sub(r"\s+", "", text)]
        elif mode == "stack":
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
    tag = re.match(r"\s*\{([^}]*)\}", body)
    if tag:
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

    mode = next((f for f in flags if f in MODES), None) or auto_mode(plain)
    starred = re.fullmatch(r"\*(.+)\*", body, re.S)
    if starred:
        body = starred.group(1)
        plain = MARK_RE.sub("", body).strip()
    dark = "dark" in flags or ("light" not in flags and index % 2 == 1)
    scene = Scene(start, end, mode, dark)
    if mode == "blank" or not plain:
        scene.mode = "blank"
        return scene

    if mode == "script":
        scene.steps = [(start, re.sub(r"\s+", " ", plain))]
    else:
        units = split_units(mode, body)
        if mode == "stack" and len(units) == 1 and "\n" not in plain and " " in plain:
            units = [[w, units[0][1] if k == 0 else None] for k, w in enumerate(plain.split())]
        if mode == "giant" and len(units) == 1:
            word = units[0][0]
            chunks = 2 if len(word) <= 4 else 3
            size = math.ceil(len(word) / chunks)
            units = [[word[k:k + size], units[0][1] if k == 0 else None] for k in range(0, len(word), size)]
        fill_times(units, start, end)
        acc = []
        for text, stamp in units:
            acc.append(text)
            if mode == "small":
                scene.steps.append((stamp, " ".join(acc)))
            elif mode == "giant":
                scene.steps.append((stamp, "".join(acc)))
            else:
                scene.steps.append((stamp, text))

    if "noghost" in flags:
        scene.ghost = None
    elif opts.get("ghost"):
        scene.ghost = opts["ghost"]
    elif mode == "stack":
        scene.ghost = scene.steps[-1][1]
    elif mode == "giant":
        scene.ghost = scene.steps[-1][1].lower()
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
    def __init__(self, width, height, fonts, light, dark):
        self.W, self.H = width, height
        self.U = min(width, height)
        self.u = self.U / 1080
        self.portrait = height > width
        self.fonts = fonts
        self.light, self.dark = light, dark
        self.ghost_room = int(60 * self.u * 8)
        self._ghost, self._giant, self._script = {}, {}, {}

    def font(self, key, size):
        return load_font(self.fonts[key], size)

    def fit(self, key, texts, size, max_w):
        widest = max((self.font(key, size).getlength(t) for t in texts), default=0)
        return size * max_w / widest if widest > max_w else size

    def shake(self, t, stamp):
        decay = clamp(1 - (t - stamp) / 0.12)
        amp = self.U * 0.01 * decay
        return amp * math.sin((t - stamp) * 95 + stamp * 7), amp * math.cos((t - stamp) * 80 + stamp * 3)

    def frame(self, scene, t):
        bg, fg = (self.dark, self.light) if scene.dark else (self.light, self.dark)
        img = Image.new("RGB", (self.W, self.H), bg)
        if scene.ghost:
            self.draw_ghost(img, scene, t, fg)
        getattr(self, f"draw_{scene.mode}")(img, scene, t, fg)
        return img

    def draw_blank(self, img, scene, t, fg):
        pass

    def draw_small(self, img, scene, t, fg):
        k = active_step(scene.steps, t)
        if k < 0:
            return
        stamp, text = scene.steps[k]
        base = self.fit("bold", [s for _, s in scene.steps], self.U * (0.16 if self.portrait else 0.17), self.W * 0.8)
        size = base * (0.8 + 0.2 * ease_out_back(clamp((t - stamp) / 0.16)))
        dx, dy = self.shake(t, stamp)
        ImageDraw.Draw(img).text(
            (self.W / 2 + dx, self.H / 2 + dy), text, font=self.font("bold", size), fill=fg, anchor="mm"
        )

    def draw_stack(self, img, scene, t, fg):
        k = active_step(scene.steps, t)
        if k < 0:
            return
        steps = scene.steps
        size = self.fit("xbold", [s for _, s in steps], self.U * (0.22 if self.portrait else 0.24), self.W * 0.88)
        font = self.font("xbold", size)
        lh = size * 0.95
        top = self.H / 2 - (len(steps) - 1) * lh / 2
        dx, dy = self.shake(t, steps[k][0])
        mask = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(mask)
        for i, (stamp, line) in enumerate(steps[: k + 1]):
            p = ease_out_cubic(clamp((t - stamp) / 0.2))
            y = top + i * lh + (1 - p) * lh * 0.45
            draw.text((self.W / 2 + dx, y + dy), line, font=font, fill=int(255 * min(1, p * 1.5)), anchor="mm")
        img.paste(fg, (0, 0), mask)

    def giant_mask(self, word, n, tw, th):
        key = (word, n)
        if key not in self._giant:
            font = self.font("anton", th * 1.2)
            left, top, right, bottom = font.getbbox(word)
            full = Image.new("L", (right - left, bottom - top), 0)
            ImageDraw.Draw(full).text((-left, -top), word, font=font, fill=255)
            cut = full.width if n >= len(word) else clamp(font.getlength(word[:n]) - left, 1, full.width)
            sx = tw / full.width
            part = full.crop((0, 0, int(cut), full.height))
            self._giant[key] = part.resize((max(1, round(cut * sx)), round(th)), Image.LANCZOS)
        return self._giant[key]

    def draw_giant(self, img, scene, t, fg):
        k = active_step(scene.steps, t)
        if k < 0:
            return
        stamp, prefix = scene.steps[k]
        word = scene.steps[-1][1]
        tw, th = self.W * 0.92, min(self.H * 0.78, self.U * 1.3)
        mask = self.giant_mask(word, len(prefix), tw, th)
        x0, y0 = (self.W - tw) / 2, (self.H - th) / 2
        punch = 1 + 0.07 * (1 - ease_out_cubic(clamp((t - stamp) / 0.14)))
        dx, dy = self.shake(t, stamp)
        if punch > 1.001:
            mask = mask.resize((max(1, int(mask.width * punch)), max(1, int(mask.height * punch))), Image.BILINEAR)
            cx, cy = self.W / 2, self.H / 2
            x0, y0 = cx + (x0 - cx) * punch, cy + (y0 - cy) * punch
        img.paste(fg, (int(x0 + dx), int(y0 + dy)), mask)

    def script_layer(self, text):
        if text not in self._script:
            size = self.fit("script", [text], self.U * (0.5 if self.portrait else 0.42), self.W * 0.86)
            mask = Image.new("L", (self.W, self.H), 0)
            ImageDraw.Draw(mask).text(
                (self.W / 2, self.H / 2), text, font=self.font("script", size), fill=255, anchor="mm"
            )
            self._script[text] = (mask, mask.getbbox() or (0, 0, 1, 1))
        return self._script[text]

    def draw_script(self, img, scene, t, fg):
        stamp, text = scene.steps[0]
        if t < stamp:
            return
        mask, (left, top, right, bottom) = self.script_layer(text)
        p = ease_out_cubic(clamp((t - stamp) / 0.7))
        width = int((right - left) * p)
        if width <= 0:
            return
        offset = int((1 - p) * self.U * 0.04)
        img.paste(fg, (left, top + offset), mask.crop((left, top, left + width, bottom)))

    def ghost_mask(self, text):
        if text not in self._ghost:
            size = self.U * 0.62
            font = self.font("anton", size)
            side = int(math.hypot(self.W, self.H) + 2 * self.ghost_room + size)
            unit = text + "   "
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
            self._ghost[text] = outline.rotate(math.degrees(0.32), resample=Image.BICUBIC)
        return self._ghost[text]

    def draw_ghost(self, img, scene, t, fg):
        mask = self.ghost_mask(scene.ghost)
        center = mask.width / 2
        drift = min(self.ghost_room, max(0.0, t - scene.start) * 60 * self.u)
        left = int(center - self.W / 2 - self.ghost_room / 2 + drift)
        top = int(center - self.H / 2)
        img.paste(fg, (0, 0), mask.crop((left, top, left + self.W, top + self.H)))


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


FORMATS = {
    "tiktok": (1080, 1920),
    "youtube": (1920, 1080),
}

QUALITIES = {
    "720p": (2 / 3, "10M"),
    "fhd": (1.0, "20M"),
    "2k": (4 / 3, "40M"),
    "4k": (2.0, "60M"),
}

# name: (label, dark background/text, light background/text)
PALETTES = {
    "wine":    ("Wine + soft pink (like Download 3)", "#3E0B2C", "#D8B4CA"),
    "maroon":  ("Maroon + taupe (like Download 2)",   "#390001", "#B19886"),
    "red":     ("Blood red + blush",                  "#5C0610", "#F3CFC8"),
    "crimson": ("Bright crimson + cream",             "#9E0B1F", "#FBE9DD"),
    "navy":    ("Navy + ice blue",                    "#0B1B3F", "#B9CDF0"),
    "royal":   ("Royal blue + white blue",            "#122C8C", "#DCE6FF"),
    "teal":    ("Deep teal + mint",                   "#06302F", "#B5E3D6"),
    "forest":  ("Forest green + sage",                "#10291C", "#C3D7B8"),
    "purple":  ("Purple + lavender",                  "#2B0F4C", "#D6C6F2"),
    "noir":    ("Black + cream",                      "#0E0E0E", "#EEE6D3"),
    "sunset":  ("Burnt brown + peach",                "#3B1405", "#FFB98A"),
    "lime":    ("Navy + lime (like Into It)",         "#0B1B3F", "#E3FF73"),
}
DEFAULT_PALETTE = "wine"


def ask_palette():
    names = list(PALETTES)
    print("\nChoose colors:")
    for i, name in enumerate(names, 1):
        label, dark, light = PALETTES[name]
        print(f"  {i:>2} = {label:<36} {dark} / {light}")
    print(f"  {len(names) + 1:>2} = Custom (type your own hex codes)")
    while True:
        answer = input(f"Choose 1-{len(names) + 1} [1]: ").strip() or "1"
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1], None, None
        if answer == str(len(names) + 1):
            dark = input("  Dark color hex (e.g. #3E0B2C): ").strip()
            light = input("  Light color hex (e.g. #D8B4CA): ").strip()
            try:
                ImageColor.getrgb(dark), ImageColor.getrgb(light)
                return "custom", dark, light
            except ValueError:
                print("  Not a valid color, try again.")
                continue
        print("  Please type a number from the list.")


def resolve_colors(args):
    """Fill args.dark / args.light from --palette, a menu, or explicit hex codes."""
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
    """Open file dialogs when no --srt is given (song first, then lyrics)."""
    if args.srt:
        return
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if not args.audio:
        args.audio = filedialog.askopenfilename(
            title="1/2  Choose the song (MP3)",
            filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"), ("All files", "*.*")],
        ) or None
        if not args.audio:
            sys.exit("No song chosen.")
    if not args.srt:
        song = Path(args.audio)
        match = next((p for p in sorted(song.parent.glob("*.srt"), key=lambda p: p.stem.lower())
                      if p.stem.lower() == song.stem.lower()), None)
        if not match:
            match = next((p for p in song.parent.glob("*.srt") if p.stem.lower().startswith(song.stem.lower())), None)
        if match:
            args.srt = str(match)
            print(f"[ok] lyrics auto-selected: {match.name}")
    if not args.srt:
        args.srt = filedialog.askopenfilename(
            title="2/2  Choose the lyrics (SRT)",
            initialdir=str(Path(args.audio).parent),
            filetypes=[("Subtitles", "*.srt"), ("All files", "*.*")],
        ) or None
        if not args.srt:
            sys.exit("No SRT chosen.")
    root.destroy()


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="SRT -> kinetic typography lyric video (TikTok or YouTube MKV).")
    parser.add_argument("--srt", help="lyrics subtitle file (.srt); a file picker opens if omitted")
    parser.add_argument("--audio", help="song file (mp3/wav/m4a); sets the video length")
    parser.add_argument("--out", help="output .MKV (default: <song name>-<format>-<size>-<fps>fps.MKV)")
    parser.add_argument("--format", choices=sorted(FORMATS), default="youtube",
                        help="youtube = 1920x1080 (16:9, default), tiktok = 1080x1920 (9:16)")
    parser.add_argument("--width", type=int, help="override width")
    parser.add_argument("--height", type=int, help="override height")
    parser.add_argument("--quality", choices=list(QUALITIES), default="fhd",
                        help="720p (10M), fhd = 1080p (20M), 2k = 1440p (40M), 4k = 2160p (60M)")
    parser.add_argument("--fps", type=int, default=60, help="30 or 60 (default 60, best for TikTok 1080p60)")
    parser.add_argument("--no-quality", action="store_true", help="skip the TikTok quality pass")
    parser.add_argument("--palette", choices=list(PALETTES) + ["custom"],
                        help="color set (a menu opens if omitted): " + ", ".join(PALETTES))
    parser.add_argument("--light", help="light color hex, overrides the palette")
    parser.add_argument("--dark", help="dark color hex, overrides the palette")
    parser.add_argument("--bitrate", help="constant video bitrate (default set by --quality: 20M / 40M / 60M at 60fps)")
    parser.add_argument("--audio-bitrate", default="256k")
    parser.add_argument("--preset", default="slow", help="x264 preset (slow = best quality)")
    parser.add_argument("--duration", type=float, help="force length in seconds")
    parser.add_argument("--fonts", default=str(here / "fonts"), help="folder for the .ttf fonts")
    parser.add_argument("--ffmpeg", help="path to ffmpeg if it is not on PATH")
    parser.add_argument("--preview", action="store_true", help="fast half-size 30fps test render")
    args = parser.parse_args()

    pick_files(args)
    resolve_colors(args)
    default_w, default_h = FORMATS[args.format]
    scale, quality_bitrate = QUALITIES[args.quality]
    default_w, default_h = round(default_w * scale / 2) * 2, round(default_h * scale / 2) * 2
    if not args.bitrate and not args.preview:
        args.bitrate = quality_bitrate if args.fps > 30 else f"{int(quality_bitrate[:-1]) * 3 // 5}M"
    args.width = args.width or default_w
    args.height = args.height or default_h
    if args.preview:
        args.width, args.height, args.preset = args.width // 2, args.height // 2, "veryfast"
    if args.fps not in (30, 60):
        sys.exit("--fps must be 30 or 60")
    base = Path(args.audio or args.srt)
    kind = f"{args.format}-preview" if args.preview else f"{args.format}-{args.width}x{args.height}-{args.fps}fps"
    suffix = f"-{args.palette}-{kind}"
    args.out = args.out or str(base.with_name(base.stem + suffix + ".MKV"))

    ffmpeg = find_ffmpeg(args.ffmpeg)
    fonts = ensure_fonts(Path(args.fonts))
    cues = read_cues(args.srt)
    if not cues:
        sys.exit(f"No subtitles found in {args.srt}")
    duration = args.duration or (probe_duration(ffmpeg, args.audio) if args.audio else None) or cues[-1][1] + 1
    light, dark = ImageColor.getrgb(args.light), ImageColor.getrgb(args.dark)
    timeline = build_timeline(cues, duration)
    kinetic = Renderer(args.width, args.height, fonts, light, dark)
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
    if not args.no_quality:
        final = quality_pass(final)
    print(f"\n[+] Finished. Output saved to:\n    {final.resolve()}")
    if os.environ.get("LYRIC_OUT_FILE"):
        Path(os.environ["LYRIC_OUT_FILE"]).write_text(str(final.resolve()), encoding="utf-8")


def quality_pass(rendered):
    """Run the bundled tiktok_quality container pass and keep only its output."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from tiktok_quality import transform
    except ImportError:
        print("[!] tiktok_quality folder missing next to lyric_video.py, keeping normal video.")
        return rendered
    final = rendered.with_name(rendered.stem + " - high tiktok.MKV")
    print("\nRunning TikTok quality pass...")
    try:
        transform(str(rendered), str(final), multiplier=10)
    except (Exception, SystemExit) as exc:
        print(f"[!] Quality pass failed ({exc}), keeping normal video.")
        final.unlink(missing_ok=True)
        return rendered
    rendered.unlink()
    return final


if __name__ == "__main__":
    main()
