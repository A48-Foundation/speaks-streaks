"""Native Discord cards and locally generated milestone animations."""

import io
import os
import random
from datetime import timedelta

import discord
from PIL import Image, ImageDraw, ImageFont

from streaks import DAYS

FIRE_TIERS = (
    (100, "blue", "Blue fire", 0x2563EB, 0x22D3EE),
    (50, "orange", "Orange fire", 0xFF6B00, 0xFFD000),
    (0, "red", "Red fire", 0xFF1744, 0xFF8A00),
)
FIRE_EMOJIS = {}
FIRE_EMOJI_PREFIX = "squolingo_fire_v2_"


def next_milestone(streak):
    return 50 if streak < 50 else 100 if streak < 100 else (streak // 100 + 1) * 100


def fire_tier(streak):
    return next(item for item in FIRE_TIERS if streak >= item[0])


def tier(streak):
    _, _, label, color, _ = fire_tier(streak)
    return label, color


def flame_badge(streak):
    _, key, label, _, _ = fire_tier(streak)
    # The label keeps tiers distinguishable if emoji upload is unavailable.
    return FIRE_EMOJIS.get(key, f"🔥 {label}")


def flame_png(color, inner_color):
    """Recolor the supplied Flaticon silhouette, retaining its transparency."""
    path = os.path.join(os.path.dirname(__file__), "assets", "flame.png")
    with Image.open(path) as source:
        image = source.convert("RGBA")
    original_outer, original_inner = (242, 104, 34), (247, 178, 25)
    outer = ((color >> 16) & 255, (color >> 8) & 255, color & 255)
    inner = ((inner_color >> 16) & 255, (inner_color >> 8) & 255, inner_color & 255)
    pixels = []
    for r, g, b, alpha in getattr(image, "get_flattened_data", image.getdata)():
        rgb = (r, g, b)
        outer_distance = sum((a - b) ** 2 for a, b in zip(rgb, original_outer))
        inner_distance = sum((a - b) ** 2 for a, b in zip(rgb, original_inner))
        pixels.append((inner if inner_distance < outer_distance else outer) + (alpha,))
    image.putdata(pixels)
    image = image.resize((128, 128), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def progress(streak):
    target = next_milestone(streak)
    filled = min(10, streak * 10 // target)
    return "▰" * filled + "▱" * (10 - filled), target


def leaderboard_embed(data, today):
    rows = [(p["name"], p["streak"], p) for p in data["participants"].values()]
    rows.extend((name, p["streak"], None) for name, p in data["legacy_scores"].items())
    rows = sorted((r for r in rows if r[1] > 0), key=lambda r: (-r[1], r[0]))
    embed = discord.Embed(title="Speaking streaks",
                          color=tier(rows[0][1] if rows else 0)[1])
    embed.set_footer(text=f"{today:%b %d, %Y} · Pacific time · Updates when you speak or freeze")
    if not rows:
        embed.description = "Your next streak starts here. Choose **My schedule**, then **Spoke**."
        return embed
    for index, (name, streak, person) in enumerate(rows[:20]):
        bar, target = progress(streak)
        if person is None:
            status = "Choose your schedule to resume"
        elif person["results"].get(today.isoformat()) == "yes":
            status = "Spoken today"
        elif person["results"].get(today.isoformat()) == "frozen":
            status = "Frozen today"
        elif today.weekday() not in person["schedule"]:
            status = "No commitment today"
        else:
            status = "Scheduled today"
        clean_name = discord.utils.escape_markdown(name.replace("\n", " ").replace("\r", " "))[:60]
        embed.add_field(
            name=f"{flame_badge(streak)} #{index + 1} {clean_name} · {streak} speaks",
            value=f"{status}\n{bar} **{streak}/{target}** · {target - streak} to go",
            inline=False,
        )
    if len(rows) > 20:
        embed.description = f"Top 20 of {len(rows)} active streaks."
    return embed


def week_embed(person, today):
    start = today - timedelta(days=today.weekday())
    lines = []
    for offset, label in enumerate(DAYS):
        day = start + timedelta(days=offset)
        result = person["results"].get(day.isoformat())
        if result == "yes":
            status = "🔥 Spoken"
        elif result == "frozen":
            status = "🧊 Frozen"
        elif offset not in person["schedule"]:
            status = "— Rest day"
        elif day < today:
            status = "○ No record"
        elif day == today:
            status = "⏳ Due today"
        else:
            status = "📅 Scheduled"
        lines.append(f"**{label.title()} {day.day}** · {status}")
    _, color = tier(person["streak"])
    embed = discord.Embed(title="📅 Your speaking week", color=color,
                          description="\n".join(lines))
    embed.add_field(name="Current streak",
                    value=f"{flame_badge(person['streak'])} **{person['streak']} speaks**")
    embed.set_footer(text="Pacific time · Unrecorded days shown against your current schedule")
    return embed


def milestone_gif(name, streak):
    """Render an original confetti animation without external image services."""
    _, color = tier(streak)
    accent = ((color >> 16) & 255, (color >> 8) & 255, color & 255)
    randomizer = random.Random(f"{name}:{streak}")
    particles = [(randomizer.randrange(640), randomizer.randrange(280),
                  randomizer.randrange(4, 9), randomizer.choice(
                      [accent, (248, 113, 113), (52, 211, 153), (96, 165, 250)]))
                 for _ in range(40)]
    title_font = ImageFont.load_default(size=44)
    name_font = ImageFont.load_default(size=25)
    small_font = ImageFont.load_default(size=18)
    frames = []
    for frame in range(20):
        image = Image.new("RGB", (640, 280), (15, 23, 42))
        draw = ImageDraw.Draw(image)
        for x, y, speed, particle_color in particles:
            y = (y + frame * speed) % 280
            draw.rectangle((x, y, x + 5, y + 9), fill=particle_color)
        draw.rounded_rectangle((42, 45, 598, 235), radius=20,
                               fill=(30, 41, 59), outline=accent, width=3)
        draw.text((320, 72), "MILESTONE UNLOCKED", font=small_font,
                  fill=accent, anchor="mt")
        draw.text((320, 103), f"{streak} DAY STREAK", font=title_font,
                  fill=(248, 250, 252), anchor="mt")
        clean_name = name.replace("\n", " ").replace("\r", " ")
        while clean_name and draw.textlength(clean_name, font=name_font) > 500:
            clean_name = clean_name[:-1]
        draw.text((320, 166), clean_name, font=name_font, fill=accent, anchor="mt")
        draw.text((320, 203), "Built one commitment at a time.", font=small_font,
                  fill=(148, 163, 184), anchor="mt")
        frames.append(image)
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:],
                   duration=70, loop=0, optimize=True)
    output.seek(0)
    return output
