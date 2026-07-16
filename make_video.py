# -*- coding: utf-8 -*-
"""
Δημιουργία κάθετου βίντεο 15 δευτερολέπτων (1080x1920) με πραγματικά βίντεο από Pexels.
Δείχνει μόνο τη φθηνότερη προσφορά (Σύνολο).
"""
import glob
import json
import os
import re
import subprocess
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
VIDEOS_DIR = os.path.join(BASE, "videos")
IMAGES_DIR = os.path.join(BASE, "city_images")
W, H = 1080, 1920
FPS = 30
CLIP_DUR = 5.0
XFADE = 0.5

FONT_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_REG = r"C:\Windows\Fonts\segoeui.ttf"

MONTHS_GR = ["", "ΙΑΝ", "ΦΕΒ", "ΜΑΡ", "ΑΠΡ", "ΜΑΪ", "ΙΟΥΝ", "ΙΟΥΛ", "ΑΥΓ", "ΣΕΠ", "ΟΚΤ", "ΝΟΕ", "ΔΕΚ"]

def gr_date(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d} {MONTHS_GR[m]}", y

def fetch_city_videos(city, country, n=3):
    """Κατεβάζει mp4 βίντεο από coverr.co (εντελώς δωρεάν, χωρίς API key)."""
    import urllib.parse
    from curl_cffi import requests
    
    folder = os.path.join(IMAGES_DIR, f"{city.lower()}_videos")
    os.makedirs(folder, exist_ok=True)
    existing = sorted(glob.glob(os.path.join(folder, "*.mp4")))
    if len(existing) >= n:
        return existing[:n]

    query = urllib.parse.quote(f"{city} {country}")
    
    print(f"[{city}] Σάρωση coverr.co...")
    r = requests.get(f"https://coverr.co/search?q={query}", impersonate="chrome124", timeout=60)
    urls = re.findall(r'https://cdn[^"\']*?\.mp4', r.text)
    
    # Φιλτράρισμα: θέλουμε 1080p και όχι paywall
    valid_urls = list(set([u for u in urls if "1080p" in u and "paywall" not in u]))
    # Αν δεν βρεθούν 1080p, παίρνουμε τα 720p κλπ
    if not valid_urls:
        valid_urls = list(set([u for u in urls if "paywall" not in u]))

    paths = []
    for i, u in enumerate(valid_urls[:n * 3]):
        if len(paths) >= n:
            break
        try:
            vid = requests.get(u, stream=True, timeout=60)
            vid.raise_for_status()
            path = os.path.join(folder, f"{len(paths):02d}.mp4")
            with open(path, "wb") as f:
                for chunk in vid.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            paths.append(path)
        except Exception:
            continue
    if not paths:
        raise RuntimeError(f"Δεν βρέθηκαν βίντεο για {city} στο Coverr")
    return paths

def make_text_overlay(trip, snap, out_png):
    from PIL import Image, ImageDraw, ImageFont
    adults = trip.get("adults", 1)
    city_gr = trip.get("name", trip["to"]).split()[0].upper()
    (d1, y1), (d2, _) = gr_date(trip["depart"]), gr_date(trip.get("return", trip["depart"]))
    
    flight = snap.get("flight_min", 0)
    stay = snap.get("booking_min", 0)
    total = flight + stay
    pp = total / adults if adults else total

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark gradient background for readability
    for y in range(H):
        alpha = int(180 * (1 - min(y, H - y) / (H / 2.5)))
        if alpha > 0:
            draw.line([(0, y), (W, y)], fill=(0, 0, 0, min(140, alpha)))

    def _text(y, text, size, fill=(255, 255, 255), bold=True):
        font = ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
        draw.text((W // 2, y), text, font=font, fill=fill, anchor="mm",
                  stroke_width=3, stroke_fill=(0, 0, 0, 200))

    _text(300, f"ΤΑΞΙΔΙ ΣΤΗ", 70, (255, 255, 255), False)
    _text(420, city_gr, 160, (255, 214, 90), True)
    _text(550, f"{d1} – {d2} {y1}", 60, (220, 220, 220), True)

    _text(1300, "ΑΠΟΛΥΤΗ ΠΡΟΣΦΟΡΑ", 60, (255, 255, 255), False)
    _text(1450, f"{total:.0f}€ ΣΥΝΟΛΟ", 140, (100, 255, 150), True)
    _text(1580, f"(Πτήσεις & Διαμονή για {adults} άτομα)", 45, (220, 220, 220), False)
    _text(1750, "🔗 ΔΕΣ ΤΑ LINKS ΣΤΗΝ ΠΕΡΙΓΡΑΦΗ", 55, (255, 255, 255), True)

    img.save(out_png)
    return out_png

def render_video(videos, overlay_png, out_mp4):
    import imageio_ffmpeg
    from curl_cffi import requests
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    
    audio_path = os.path.join(BASE, "bg_music.mp3")
    if not os.path.exists(audio_path):
        r = requests.get("https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Tours/Enthusiast/Tours_-_01_-_Enthusiast.mp3", impersonate="chrome124")
        with open(audio_path, "wb") as f: f.write(r.content)
        
    inputs = []
    filters = []
    
    n = len(videos)
    for i, v in enumerate(videos):
        inputs += ["-i", v]
        # Crop to vertical, trim to 5s
        filters.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},trim=0:{CLIP_DUR},setpts=PTS-STARTPTS,fps={FPS}[v{i}]")
    
    # Xfade videos
    last = "[v0]"
    for i in range(1, n):
        out = f"[x{i}]" if i < n - 1 else "[vbase]"
        offset = i * CLIP_DUR - i * XFADE
        filters.append(f"{last}[v{i}]xfade=transition=fade:duration={XFADE}:offset={offset:.2f}{out}")
        last = out
        
    if n == 1:
        filters.append("[v0]copy[vbase]")

    inputs += ["-i", overlay_png, "-stream_loop", "-1", "-i", audio_path]
    idx_overlay = n
    idx_audio = n + 1
    
    # Overlay PNG on top of stitched videos
    filters.append(f"[vbase][{idx_overlay}:v]overlay=0:0[vout]")

    cmd = [ffmpeg, "-y", *inputs,
           "-filter_complex", ";".join(filters),
           "-map", "[vout]", "-map", f"{idx_audio}:a", 
           "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-shortest",
           "-r", str(FPS), "-movflags", "+faststart", out_mp4]
    
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + res.stderr)

def main():
    args = sys.argv[1:]
    with open(os.path.join(BASE, "trips.json"), encoding="utf-8") as f:
        trips = {t["id"]: t for t in json.load(f)["trips"] if t.get("enabled", True)}

    snaps = sorted(glob.glob(os.path.join(BASE, "snapshots", "*.json")))
    if not snaps:
        return 1
    with open(snaps[-1], encoding="utf-8") as f:
        snapshot = json.load(f)

    ids = [a for a in args if a in trips] if (args and args[0] != "--all") else list(trips)

    os.makedirs(VIDEOS_DIR, exist_ok=True)
    for tid in ids:
        trip, snap = trips[tid], snapshot.get(tid, {})
        if not snap.get("flight_min") and not snap.get("booking_min"):
            continue
            
        print(f"[{tid}] Λήψη Pexels Videos...")
        # Use country logic to prevent Colosseum in Vienna
        country = "Austria" if "vie" in tid else "Spain"
        vids = fetch_city_videos(trip.get("city") or trip["to"], country, n=3)
        
        print(f"[{tid}] Δημιουργία overlay...")
        out_dir = os.path.join(VIDEOS_DIR, "_slides_" + tid)
        os.makedirs(out_dir, exist_ok=True)
        overlay = make_text_overlay(trip, snap, os.path.join(out_dir, "overlay.png"))
        
        print(f"[{tid}] Rendering βίντεο (15s)...")
        out_mp4 = os.path.join(VIDEOS_DIR, f"{tid}_{date.today().isoformat()}.mp4")
        render_video(vids, overlay, out_mp4)
        print(f"[{tid}] ✅ {out_mp4}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
