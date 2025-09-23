#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import st7789 as st7789
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import requests, time, sys
import pytz
from pathlib import Path
import subprocess
from dotenv import load_dotenv
load_dotenv()

# Define California timezone
tz = pytz.timezone(os.getenv("RUSH_NOTI_TIMEZONE"))

# ---------------- Display setup ----------------
disp = st7789.ST7789(
    width=320,
    height=240,
    rotation=180,
    port=0,
    cs=1,
    dc=9,
    backlight=13,
    spi_speed_hz=80 * 1000 * 1000,
)
disp.begin()

# --- audio setup ---
ALSA_DEVICE = "default"  # or "hw:0,0"
SOUND_DIR = Path(os.getenv("RUSH_NOTI_SOUND_DIR"))
ORDER_WAV = SOUND_DIR / "order.wav"
DING_WAV  = SOUND_DIR / "ding.wav"

W, H = 320, 240
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED   = (150, 30, 30)

# Play sound
def play_wav(path: Path):
    if not path.exists():
        print(f"[audio][warn] missing: {path}")
        return
    subprocess.Popen(
        ["aplay", "-q", "-D", ALSA_DEVICE, str(path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

# Load fonts
def load_font(name, size):
    try:
        return ImageFont.truetype(name, size)
    except Exception:
        return ImageFont.load_default()

FONT_LABEL = load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 21)
FONT_NUM   = load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
FONT_NUM_M = load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 25)
FONT_TIME  = load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)

def center_text(draw, box, text, font, fill):
    x0, y0, x1, y1 = box
    w, h = draw.textbbox((0, 0), text, font=font)[2:]
    draw.text((x0 + (x1 - x0 - w)/2, y0 + (y1 - y0 - h)/2), text, font=font, fill=fill)

def draw_dashboard(orders, offline, total_str, quotes, signup, timestamp_str):
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # Grid
    mid = W // 2
    grid_h = H - 24
    d.line([(mid, 0), (mid, grid_h)], fill=BLACK, width=2)
    d.line([(0, grid_h//2), (W, grid_h//2)], fill=BLACK, width=2)
    d.rectangle([(0, H-24), (W, H)], fill=BLACK)

    # Quadrants
    q1 = (0, 0, mid, grid_h//2)
    q2 = (mid, 0, W, grid_h//2)
    q3 = (0, grid_h//2, mid, grid_h)
    q4 = (mid, grid_h//2, W, grid_h)

    def draw_cell(box, label, value, small_value=False):
        x0, y0, x1, y1 = box
        d.text((x0 + 10, y0 + 6), label, font=FONT_LABEL, fill=BLACK)
        font_val = FONT_NUM_M if small_value else FONT_NUM
        w, h = d.textbbox((0, 0), value, font=font_val)[2:]
        cx = x0 + (x1 - x0 - w) / 2
        cy = y0 + (y1 - y0 - h) / 2 + 10
        d.text((cx, cy), value, font=font_val, fill=RED)

    draw_cell(q1, "Offline", str(offline))
    draw_cell(q2, f"Orders({orders})", total_str, small_value=True)
    draw_cell(q3, "Quotes", str(quotes))
    draw_cell(q4, "Signup", str(signup))

    center_text(d, (0, H-24, W, H), timestamp_str, FONT_TIME, WHITE)
    return img

def ordinal(n):
    return "%d%s" % (n, "th" if 11<=n%100<=13 else {1:"st",2:"nd",3:"rd"}.get(n%10, "th"))

def fetch_stats():
    try:
        r = requests.get(os.getenv("RUSH_NOTI_API"), timeout=10)
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "ok":
            raise ValueError("API status not ok")
        data = j["data"]
        return {
            "orders": data["orders"],
            "offline": data["offline_quotes"],
            "total": data["orders_total_formatted"],
            "quotes": data["quotes"],
            "signup": data["registrations"]
        }
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return None

def draw_message(text):
    img = Image.new("RGB", (W, H), BLACK)  # black background
    d = ImageDraw.Draw(img)
    center_text(d, (0, 0, W, H), text, FONT_LABEL, WHITE)
    return img

# -------- Loop --------
last = None  # remember last values to detect increases

while True:
    stats = fetch_stats()
    if stats:
        # --- detect increases vs previous tick ---
        if last is not None:
            try:
                if stats["orders"] > last["orders"]:
                    play_wav(ORDER_WAV)
                # any of these increments -> ding.wav
                if stats["offline"] > last["offline"]:
                    play_wav(DING_WAV)
                if stats["quotes"] > last["quotes"]:
                    play_wav(DING_WAV)
                if stats["signup"] > last["signup"]:
                    play_wav(DING_WAV)
            except Exception as e:
                print(f"[audio][error] {e}")

        # --- render display ---
        now = datetime.now(tz)  # you already defined tz = America/Los_Angeles
        timestamp = f"{ordinal(now.day)} {now.strftime('%b')}, {now.strftime('%-I:%M %p').lower()}"
        img = draw_dashboard(
            orders=stats["orders"],
            offline=stats["offline"],
            total_str=stats["total"],
            quotes=stats["quotes"],
            signup=stats["signup"],
            timestamp_str=timestamp
        )
        disp.display(img)
        print(f"[update] {stats} at {timestamp}")

        # remember for next comparison
        last = stats
    else:
        # No network / API error
        img = draw_message("No Network Connection\n\nPlease unplug and plug\ndevice then connect to\n'Rush-Noti Setup' WiFi\nselect your network and\nenter your wifi password")
        disp.display(img)

    time.sleep(60)
