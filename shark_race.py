"""Original pixel-art sharks, with live streaks on a shared race scale."""

import hashlib
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SHARK_COLORS = (
    "#28e1ef", "#b995ff", "#ffb953", "#ff729e", "#6be5a2", "#78aaff",
    "#f77c55", "#f1df65", "#e586eb", "#55d5c3", "#a7dc68", "#e5c5a3",
)
SHARK_KINDS = ("reef", "hammerhead", "tiger", "whale")
SCALE = 2


def shark_style(name):
    digest = hashlib.sha256(name.casefold().encode("utf-8")).digest()
    return SHARK_COLORS[digest[0] % len(SHARK_COLORS)], SHARK_KINDS[digest[1] % len(SHARK_KINDS)]


def race_rows(data, today):
    rows = []
    for person in data["participants"].values():
        result = person["results"].get(today.isoformat())
        status = "Spoken" if result == "yes" else "Frozen" if result == "frozen" else "Scheduled"
        rows.append((person["name"], person["streak"], status))
    rows.extend((name, person["streak"], "Scheduled")
                for name, person in data["legacy_scores"].items())
    return sorted((row for row in rows if row[1] > 0), key=lambda row: (-row[1], row[0]))[:20]


def race_attachments(data, today):
    rows = race_rows(data, today)
    if not rows:
        return []
    goal = max(300, (max(row[1] for row in rows) // 100 + 1) * 100)
    images = []
    for offset in range(0, len(rows), 5):
        frames = shark_race_gif(rows[offset:offset + 5], goal, rank_offset=offset)
        output = io.BytesIO()
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:],
                       duration=200, loop=0, optimize=True)
        images.append(output.getvalue())
    return images


def shark_race_gif(rows, goal=300, rank_offset=0):
    """Use one shared scale; animation never changes a shark's streak position."""
    if goal <= 0 or not rows or any(streak < 0 or streak > goal for _, streak, _ in rows):
        raise ValueError("Provide racers with streaks between zero and the shared goal.")
    width, height = 512, 105 + 55 * len(rows)
    start, finish = 160, 434
    marks = sorted({mark for mark in (0, 10, 50, 100, 200, goal) if mark <= goal})
    frames = []
    font = ImageFont.load_default(size=10)
    small = ImageFont.load_default(size=8)
    title = ImageFont.load_default(size=18)
    status_font = ImageFont.truetype(
        str(Path(__file__).parent / "assets" / "Silkscreen-Regular.ttf"), 24)
    for frame in range(12):
        image = Image.new("RGB", (width, height), "#071624")
        draw = ImageDraw.Draw(image)
        draw.fontmode = "1"
        for y in range(0, height, 4):
            draw.line((0, y, width, y), fill="#091b2a")
        draw.text((14, 10), "SQUOLINGO", font=title, fill="#e5fbff")
        for mark in marks:
            x = start + round(mark / goal * (finish - start))
            draw.text((x, 55), str(mark), font=small, fill="#97bed0", anchor="mt")
        draw.text((450, 55), "STREAK", font=small, fill="#97bed0")
        for rank, (name, streak, status) in enumerate(rows):
            top = 71 + rank * 55
            center = top + 24
            accent, kind = shark_style(name)
            draw.rectangle((12, top, 499, top + 49), fill="#102839", outline="#204457")
            clean_name = name.replace("\n", " ").replace("\r", " ")[:60]
            name_label = f"{rank + rank_offset + 1:02}  {clean_name}"
            while draw.textlength(name_label, font=font) > 106:
                clean_name = clean_name[:-1]
                name_label = f"{rank + rank_offset + 1:02}  {clean_name}..."
            draw.text((20, top + 7), name_label, font=font, fill="#e5fbff")
            draw.line((start, center + 14, finish, center + 14), fill="#2c576b")
            for mark in marks[:-1]:
                x = start + round(mark / goal * (finish - start))
                for y in range(top + 4, top + 45, 6):
                    draw.line((x, y, x, y + 2), fill="#244456")
            for y in range(top + 4, top + 45, 4):
                for column in range(2):
                    draw.rectangle((finish + column * 4, y, finish + column * 4 + 3, y + 3),
                                   fill="#c7e8ed" if (y // 4 + column) % 2 else "#183f54")
            nose = start + round(streak / goal * (finish - start))
            tail_shift = (0, 2, 0, -2)[frame // 3]
            for bubble in range(4):
                x = nose - 40 - bubble * 9
                y = center + 9 - ((frame * 2 + bubble * 5) % 24)
                if x >= 133:
                    draw.rectangle((x, y, x + 2, y + 2), outline="#418397")
            draw.polygon([(nose - 27, center), (nose - 38, center - 9 + tail_shift),
                          (nose - 36, center), (nose - 38, center + 9 + tail_shift)],
                         fill=accent)
            draw.polygon([(nose - 24, center - 5), (nose - 18, center - 14),
                          (nose - 14, center - 5)], fill=accent)
            draw.polygon([(nose - 28, center - 5), (nose - 9, center - 7),
                          (nose - 2, center - 3), (nose, center + 2),
                          (nose - 7, center + 7), (nose - 25, center + 6),
                          (nose - 30, center)], fill=accent)
            if kind == "whale":
                draw.polygon([(nose - 28, center - 6), (nose - 17, center - 10),
                              (nose - 5, center - 8), (nose, center - 4),
                              (nose, center + 5), (nose - 10, center + 8),
                              (nose - 27, center + 7)], fill=accent)
                for x in (nose - 25, nose - 20, nose - 15):
                    draw.rectangle((x, center - 6, x + 1, center - 5), fill="#e5fbff")
                    draw.point((x + 2, center - 2), fill="#e5fbff")
            draw.polygon([(nose - 27, center + 1), (nose - 5, center + 2),
                          (nose - 8, center + 6), (nose - 25, center + 5)],
                         fill="#c8f4f2")
            draw.polygon([(nose - 19, center + 3), (nose - 21, center + 11),
                          (nose - 12, center + 5)], fill="#3997b3")
            draw.rectangle((nose - 9, center - 3, nose - 7, center - 1), fill="#061722")
            draw.point((nose - 9, center - 3), fill="#ffffff")
            draw.line((nose - 6, center + 3, nose - 2, center + 2), fill="#14516a")
            if kind == "tiger":
                draw.polygon([(nose - 25, center - 6), (nose - 19, center - 17),
                              (nose - 13, center - 6)], fill=accent)
            elif kind == "hammerhead":
                draw.rectangle((nose - 9, center - 11, nose - 1, center + 10), fill=accent)
                draw.rectangle((nose - 6, center - 9, nose - 4, center - 7), fill="#061722")
                draw.rectangle((nose - 6, center + 6, nose - 4, center + 8), fill="#061722")
                draw.line((nose - 1, center - 5, nose - 1, center + 4), fill="#c8f4f2")
            if status == "Frozen":
                draw.rectangle((nose - 40, center - 17, nose + 4, center + 16),
                               outline="#9cf4ff", width=2)
                draw.line((nose - 35, center - 13, nose - 23, center - 13), fill="#e5fcff")
                draw.line((nose, center + 4, nose, center + 11), fill="#e5fcff")
                draw.line((nose - 5, center - 16, nose - 10, center - 8), fill="#78cbe4")
            draw.text((475, center - 2), str(streak), font=title, fill=accent, anchor="mm")
        bottom = 71 + len(rows) * 55
        for x in range(18, 497, 8):
            draw.rectangle((x, bottom + 11, x + 3, height - 1), fill="#193c46")
            coral_height = int(4 + 4 * math.sin(x))
            draw.rectangle((x, bottom + 11 - coral_height, x + 3, bottom + 13),
                           fill="#33706a" if x % 3 else "#b77477")
        image = image.resize((width * SCALE, height * SCALE), Image.Resampling.NEAREST)
        text = ImageDraw.Draw(image)
        text.fontmode = "1"
        for rank, (_, _, status) in enumerate(rows):
            label = {"Spoken": "spoke today", "Frozen": "frozen"}.get(status, "not yet")
            text.text((20 * SCALE, (71 + rank * 55 + 24) * SCALE), label,
                      font=status_font, fill="#d2e7f2")
        frames.append(image)
    return frames
