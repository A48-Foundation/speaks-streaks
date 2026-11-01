import unittest
from datetime import date

from PIL import Image

from streak_display import leaderboard_embed, milestone_gif, next_milestone, week_embed
from streaks import new_person


class DisplayTests(unittest.TestCase):
    def test_progress_advances_to_the_next_major_milestone(self):
        self.assertEqual([next_milestone(n) for n in (49, 50, 100, 232, 300)],
                         [50, 100, 200, 300, 400])
        data = {"participants": {}, "legacy_scores": {"Aanya": {"streak": 232}}}
        embed = leaderboard_embed(data, date(2026, 11, 1))
        self.assertIn("232/300", embed.fields[0].value)
        self.assertIn("68 to go", embed.fields[0].value)
        self.assertIn("Gold", embed.fields[0].value)

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


if __name__ == "__main__":
    unittest.main()
