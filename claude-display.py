#!/usr/bin/env python3

import json
import os
import signal
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from library.lcd.lcd_comm_rev_a import LcdCommRevA, Orientation
from library.log import logger


COM_PORT = "/dev/cu.usbmodemUSB35INCHIPSV21"

# Turing/TURZX 3.5-inch Rev A uses portrait dimensions internally.
# We rotate it to landscape below.
WIDTH, HEIGHT = 320, 480

DATA_FILE = Path.home() / ".claude" / "quota-meter" / "current.json"
BACKGROUND = "/tmp/claude-turzx-background.png"

PACIFIC = ZoneInfo("America/Los_Angeles")

ACTIVE_BRIGHTNESS = 18
IDLE_BRIGHTNESS = 4
STALE_SECONDS = 180

stop = False


def sighandler(signum, frame):
    global stop
    stop = True


def clamp(value, low=0, high=100):
    try:
        value = int(value)
    except Exception:
        value = 0

    return max(low, min(high, value))


def load_snapshot():
    if not DATA_FILE.exists():
        return None

    try:
        with DATA_FILE.open("r") as f:
            return json.load(f)
    except Exception:
        return None


def reset_time_label(epoch_seconds):
    """
    Converts Claude's Unix reset timestamp to a compact Pacific time label.

    Example:
    Tue 5:42 PM PT
    """
    try:
        epoch_seconds = int(epoch_seconds)
    except Exception:
        return "--"

    if epoch_seconds <= 0:
        return "--"

    reset_dt = datetime.fromtimestamp(epoch_seconds, tz=PACIFIC)

    day = reset_dt.strftime("%a")
    hour = reset_dt.strftime("%I").lstrip("0")
    minute = reset_dt.strftime("%M")
    ampm = reset_dt.strftime("%p")

    return f"{day} {hour}:{minute} {ampm} PT"


def color_for_remaining(remaining):
    remaining = clamp(remaining)

    if remaining <= 10:
        return (255, 50, 50)

    if remaining <= 25:
        return (255, 145, 40)

    if remaining <= 50:
        return (255, 215, 70)

    return (90, 230, 120)


def make_background(width, height):
    img = Image.new("RGB", (width, height), (8, 10, 14))
    draw = ImageDraw.Draw(img)

    # Section separators for the 320x480 portrait screen.
    draw.line((18, 86, width - 18, 86), fill=(38, 42, 50), width=2)
    draw.line((18, 228, width - 18, 228), fill=(38, 42, 50), width=2)
    draw.line((18, 370, width - 18, 370), fill=(38, 42, 50), width=2)

    img.save(BACKGROUND)


def text(
    lcd,
    value,
    x,
    y,
    size=20,
    color=(245, 245, 245),
    font="res/fonts/roboto/Roboto-Bold.ttf",
):
    lcd.DisplayText(
        str(value),
        x,
        y,
        font=font,
        font_size=size,
        font_color=color,
        background_image=BACKGROUND,
    )


def bar(lcd, x, y, width, height, value, color):
    lcd.DisplayProgressBar(
        x,
        y,
        width=width,
        height=height,
        min_value=0,
        max_value=100,
        value=clamp(value),
        bar_color=color,
        bar_outline=True,
        background_image=BACKGROUND,
    )


def render(lcd, snap):
    now = int(time.time())
    stale = True

    if snap:
        stale = now - int(snap.get("updated_at", 0)) > STALE_SECONDS

    lcd.DisplayBitmap(BACKGROUND)
    lcd.SetBrightness(IDLE_BRIGHTNESS if stale else ACTIVE_BRIGHTNESS)

    if not snap:
        text(lcd, "CLAUDE", 18, 20, size=32)
        text(
            lcd,
            "waiting for",
            18,
            90,
            size=22,
            color=(170, 178, 190),
            font="res/fonts/roboto/Roboto-Regular.ttf",
        )
        text(lcd, "Claude Code", 18, 120, size=30)
        text(
            lcd,
            "open Claude to wake",
            18,
            210,
            size=18,
            color=(125, 132, 145),
            font="res/fonts/roboto/Roboto-Regular.ttf",
        )
        return

    if stale:
        text(lcd, "CLAUDE IDLE", 18, 20, size=28, color=(170, 178, 190))
        text(
            lcd,
            "no recent update",
            18,
            88,
            size=22,
            color=(125, 132, 145),
            font="res/fonts/roboto/Roboto-Regular.ttf",
        )
        text(lcd, "start Claude Code", 18, 120, size=24)
        text(lcd, "to wake display", 18, 150, size=24)
        return

    model = snap.get("model", "Claude")
    project = snap.get("project", "")

    five = snap.get("five_hour", {})
    week = snap.get("seven_day", {})
    ctx = snap.get("context_window", {})

    five_remaining = clamp(five.get("remaining", 0))
    week_remaining = clamp(week.get("remaining", 0))
    ctx_remaining = clamp(ctx.get("remaining", 0))

    five_color = color_for_remaining(five_remaining)
    week_color = color_for_remaining(week_remaining)
    ctx_color = color_for_remaining(ctx_remaining)

    model_label = model.replace("Claude ", "")

    text(lcd, "CLAUDE", 18, 14, size=30)
    text(
        lcd,
        model_label,
        18,
        52,
        size=16,
        color=(145, 152, 165),
        font="res/fonts/roboto/Roboto-Regular.ttf",
    )

    # 5-hour limit.
    text(
        lcd,
        "5-HOUR",
        18,
        102,
        size=18,
        color=(170, 178, 190),
        font="res/fonts/roboto/Roboto-Regular.ttf",
    )
    text(lcd, f"{five_remaining}% LEFT", 18, 124, size=34, color=five_color)
    bar(lcd, 18, 172, 284, 18, five_remaining, five_color)
    text(
        lcd,
        f"resets {reset_time_label(five.get('resets_at', 0))}",
        18,
        196,
        size=16,
        color=(145, 152, 165),
        font="res/fonts/roboto/Roboto-Regular.ttf",
    )

    # Weekly limit.
    text(
        lcd,
        "WEEK",
        18,
        244,
        size=18,
        color=(170, 178, 190),
        font="res/fonts/roboto/Roboto-Regular.ttf",
    )
    text(lcd, f"{week_remaining}% LEFT", 18, 266, size=34, color=week_color)
    bar(lcd, 18, 314, 284, 18, week_remaining, week_color)
    text(
        lcd,
        f"resets {reset_time_label(week.get('resets_at', 0))}",
        18,
        338,
        size=16,
        color=(145, 152, 165),
        font="res/fonts/roboto/Roboto-Regular.ttf",
    )

    # Context window.
    text(
        lcd,
        "CTX",
        18,
        386,
        size=16,
        color=(170, 178, 190),
        font="res/fonts/roboto/Roboto-Regular.ttf",
    )
    text(lcd, f"{ctx_remaining}% left", 70, 384, size=20, color=ctx_color)
    bar(lcd, 18, 414, 284, 14, ctx_remaining, ctx_color)

    footer = project or "Claude Code"

    if len(footer) > 28:
        footer = footer[:25] + "..."

    updated_label = datetime.now(PACIFIC).strftime("%a %-I:%M %p PT")

    text(
        lcd,
        footer,
        18,
        448,
        size=16,
        color=(125, 132, 145),
        font="res/fonts/roboto/Roboto-Regular.ttf",
    )

    text(
        lcd,
        updated_label,
        18,
        468,
        size=14,
        color=(90, 96, 108),
        font="res/fonts/roboto/Roboto-Regular.ttf",
    )


def main():
    signal.signal(signal.SIGINT, sighandler)
    signal.signal(signal.SIGTERM, sighandler)

    if os.name == "posix":
        signal.signal(signal.SIGQUIT, sighandler)

    lcd = LcdCommRevA(
        com_port=COM_PORT,
        display_width=WIDTH,
        display_height=HEIGHT,
    )

    lcd.Reset()
    lcd.InitializeComm()
    lcd.SetBrightness(level=ACTIVE_BRIGHTNESS)
    lcd.SetBackplateLedColor(led_color=(255, 255, 255))
    lcd.SetOrientation(orientation=Orientation.PORTRAIT)

    make_background(lcd.get_width(), lcd.get_height())

    logger.info("Starting Claude TURZX display")

    last_signature = None

    while not stop:
        snap = load_snapshot()
        now = int(time.time())
        stale = snap is None or now - int(snap.get("updated_at", 0)) > STALE_SECONDS

        # Redraw only when the underlying data or stale/active state has
        # actually changed, so the screen doesn't flicker every poll.
        signature = (stale, json.dumps(snap, sort_keys=True) if snap else None)

        if signature != last_signature:
            render(lcd, snap)
            last_signature = signature

        time.sleep(10)

    logger.info("Closing Claude TURZX display")
    lcd.SetBrightness(level=0)
    lcd.closeSerial()


if __name__ == "__main__":
    main()