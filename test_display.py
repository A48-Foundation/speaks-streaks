import unittest
import io
import tempfile
from datetime import date
from unittest.mock import patch

from PIL import Image, ImageColor

from streak_display import (
    FIRE_EMOJIS, flame_png, leaderboard_embed, milestone_gif, next_milestone, week_embed,
)
from streaks import new_person
from race_preview import render_preview
from shark_race import SCALE, race_attachments, race_rows, shark_race_gif, shark_style


class DisplayTests(unittest.TestCase):
    def test_race_uses_shared_scale_and_animation_keeps_streak_positions_fixed(self):
        frames = shark_race_gif([("Leader", 232, "Spoken"), ("Runner", 61, "Frozen")])
        for lane, streak in enumerate((232, 61)):
            nose = 160 + round(streak / 300 * (434 - 160))
            center = 71 + lane * 55 + 24
            color = ImageColor.getrgb(shark_style(("Leader", "Runner")[lane])[0])
            for frame in frames:
                self.assertEqual(frame.getpixel((nose * SCALE, (center + 2) * SCALE)), color)
        self.assertNotEqual(frames[0].tobytes(), frames[1].tobytes())

    def test_race_preview_writes_offline_animation_and_still(self):
        with tempfile.TemporaryDirectory() as folder:
            page = render_preview(folder)
            self.assertIn("Preview buttons are inactive", page.read_text(encoding="utf-8"))
            with Image.open(page.with_name("shark-race.gif")) as animation:
                self.assertEqual(animation.size, (1024, 1420))
                self.assertEqual(animation.n_frames, 12)
                self.assertEqual(animation.info["loop"], 0)
            with Image.open(page.with_name("shark-race.png")) as still:
                self.assertEqual(still.size, (1024, 1420))

    def test_race_statuses_are_drawn_beneath_names(self):
        with patch("shark_race.ImageDraw.ImageDraw.text") as text:
            shark_race_gif([("A", 232, "Spoken"), ("B", 61, "Frozen"),
                            ("C", 15, "Scheduled")])
        calls = [(call.args[0], call.args[1]) for call in text.call_args_list]
        for lane, (name, status) in enumerate((("A", "spoke today"), ("B", "frozen"),
                                              ("C", "not yet"))):
            top = 71 + lane * 55
            self.assertIn(((20, top + 7), f"{lane + 1:02}  {name}"), calls)
            self.assertIn(((20 * SCALE, (top + 24) * SCALE), status), calls)
        status_calls = [call for call in text.call_args_list
                        if call.args[1] in ("spoke today", "frozen", "not yet")]
        self.assertTrue(all("Silkscreen" in call.kwargs["font"].getname()[0]
                            for call in status_calls))

    def test_race_draws_ten_and_fifty_day_lines_in_each_lane(self):
        frame = shark_race_gif([("Leader", 232, "Spoken"), ("Runner", 61, "Frozen")])[0]
        for lane in range(2):
            for mark in (10, 50):
                x = 160 + round(mark / 300 * (434 - 160))
                y = 71 + lane * 55 + 4
                self.assertEqual(frame.getpixel((x * SCALE, y * SCALE)), (36, 68, 86))

    def test_live_race_uses_today_records_hides_zero_and_pages_shared_scale(self):
        today = date(2026, 11, 1)
        spoken = new_person("Spoken", [6], today, 500)
        spoken["results"][today.isoformat()] = "yes"
        frozen = new_person("Frozen", [6], today, 100)
        frozen["results"][today.isoformat()] = "frozen"
        data = {"participants": {"1": spoken, "2": frozen},
                "legacy_scores": {f"Runner {n}": {"streak": n} for n in range(5)}}
        rows = race_rows(data, today)
        self.assertEqual(rows[:2], [("Spoken", 500, "Spoken"), ("Frozen", 100, "Frozen")])
        self.assertEqual(len(rows), 6)
        with patch("shark_race.shark_race_gif", wraps=shark_race_gif) as render:
            images = race_attachments(data, today)
        self.assertEqual(len(images), 2)
        self.assertEqual([call.args[1] for call in render.call_args_list], [600, 600])
        self.assertEqual([call.kwargs["rank_offset"] for call in render.call_args_list], [0, 5])
        with Image.open(io.BytesIO(images[0])) as image:
            self.assertEqual(image.size, (1024, 760))
            self.assertLess(len(images[0]), 8 * 1024 * 1024)

    def test_shark_identity_and_appearance_survive_rank_changes(self):
        original = shark_race_gif([("Debater", 100, "Spoken")])[0]
        reordered = shark_race_gif([("Other", 200, "Spoken"), ("Debater", 100, "Spoken")])[0]
        nose = 160 + round(100 / 300 * (434 - 160))
        box = ((nose - 40) * SCALE, (71 + 6) * SCALE,
               (nose + 5) * SCALE, (71 + 42) * SCALE)
        shifted = (box[0], box[1] + 55 * SCALE, box[2], box[3] + 55 * SCALE)
        self.assertEqual(original.crop(box).tobytes(), reordered.crop(shifted).tobytes())

    def test_race_rejects_scores_outside_shared_track(self):
        for rows, goal in (([], 300), ([("Debater", -1, "Spoken")], 300),
                           ([("Debater", 301, "Spoken")], 300),
                           ([("Debater", 1, "Spoken")], 0)):
            with self.assertRaises(ValueError):
                shark_race_gif(rows, goal)

    def test_progress_advances_to_the_next_major_milestone(self):
        self.assertEqual([next_milestone(n) for n in (49, 50, 100, 232, 300)],
                         [50, 100, 200, 300, 400])
        data = {"participants": {}, "legacy_scores": {"Aanya": {"streak": 232}}}
        embed = leaderboard_embed(data, date(2026, 11, 1))
        self.assertIn("232/300", embed.fields[0].value)
        self.assertIn("68 to go", embed.fields[0].value)
        self.assertNotIn("Gold", embed.fields[0].value)

    def test_card_orders_positive_streaks_and_shows_daily_status(self):
        today = date(2026, 11, 1)
        person = new_person("Leader", [6], today, 61)
        person["results"][today.isoformat()] = "frozen"
        data = {"participants": {"1": person},
                "legacy_scores": {"Hidden": {"streak": 0}, "Runner": {"streak": 15}}}
        embed = leaderboard_embed(data, today)
        self.assertIn("Leader", embed.fields[0].name)
        self.assertIn("Frozen today", embed.fields[0].value)
        self.assertIn("Runner", embed.fields[1].name)
        self.assertNotIn("Hidden", str(embed.to_dict()))

    def test_large_leaderboard_stays_within_discord_embed_limits(self):
        data = {"participants": {}, "legacy_scores": {
            f"Debater {index} " + "*" * 50: {"streak": index + 1} for index in range(100)
        }}
        embed = leaderboard_embed(data, date(2026, 11, 1))
        self.assertLessEqual(len(embed), 6000)
        self.assertLessEqual(len(embed.fields), 25)
        self.assertIn("Top 20 of 100", embed.description)

    def test_week_shows_actual_completed_and_frozen_days(self):
        today = date(2026, 10, 22)
        person = new_person("Debater", [1, 3], today, 20)
        person["results"] = {"2026-10-20": "yes", "2026-10-22": "frozen"}
        embed = week_embed(person, today)
        self.assertIn("Tue 20** · 🔥 Spoken", embed.description)
        self.assertIn("Thu 22** · 🧊 Frozen", embed.description)
        self.assertIn("Wed 21** · — Rest day", embed.description)
        self.assertIn("current schedule", embed.footer.text)

    def test_milestone_animation_is_a_valid_multiframe_gif(self):
        animation = milestone_gif("Neo 蔡", 200)
        image = Image.open(animation)
        self.assertEqual(image.format, "GIF")
        self.assertEqual(image.size, (640, 280))
        self.assertEqual(image.n_frames, 20)
        image.seek(0)
        first = image.convert("RGB").tobytes()
        image.seek(1)
        self.assertNotEqual(first, image.convert("RGB").tobytes())
        self.assertLess(len(animation.getvalue()), 8 * 1024 * 1024)

    def test_single_flame_badge_red_standard_and_blue_at_100(self):
        data = {"participants": {}, "legacy_scores": {
            "Standard": {"streak": 15}, "Highest": {"streak": 100},
            "Almost": {"streak": 99},
        }}
        with patch.dict(FIRE_EMOJIS, {"red": "<:red_fire:1>", "blue": "<:blue_fire:2>",
                                     "orange": "<:orange_fire:3>"}):
            embed = leaderboard_embed(data, date(2026, 11, 1))
        self.assertIn("<:blue_fire:2>", embed.fields[0].name)
        self.assertIn("<:orange_fire:3>", embed.fields[1].name)
        self.assertIn("<:red_fire:1>", embed.fields[2].name)
        for field in embed.fields:
            self.assertEqual(field.name.count("<:"), 1)
            self.assertNotIn("fire", field.value)
        for medal in ("🥇", "🥈", "🥉", "🏆", "💎"):
            self.assertNotIn(medal, str(embed.to_dict()))

    def test_generated_red_and_blue_flames_are_distinct_transparent_pngs(self):
        red = Image.open(io.BytesIO(flame_png(0xFF1744, 0xFF8A00)))
        blue = Image.open(io.BytesIO(flame_png(0x2563EB, 0x22D3EE)))
        self.assertEqual(red.mode, "RGBA")
        self.assertEqual(red.getpixel((0, 0))[3], 0)
        self.assertNotEqual(red.tobytes(), blue.tobytes())
        for image, outer, inner in ((red, (255, 23, 68), (255, 138, 0)),
                                    (blue, (37, 99, 235), (34, 211, 238))):
            colors = {color[:3] for count, color in image.getcolors(128 * 128)
                      if color[3] == 255 and count > 100}
            self.assertIn(outer, colors)
            self.assertIn(inner, colors)


if __name__ == "__main__":
    unittest.main()
