import asyncio
import unittest
from datetime import date
from unittest.mock import AsyncMock, Mock, patch

from streaks import new_person, parse_schedule, reconcile, record
from test_persistence import bot


class StreakTests(unittest.TestCase):
    def test_scheduled_days_only_and_current_day_grace(self):
        person = new_person("Debater", [1, 3], date(2026, 10, 20), 10)
        record(person, date(2026, 10, 20), "yes")  # Tuesday
        reconcile(person, date(2026, 10, 22))  # Thursday, Wednesday ignored
        self.assertEqual(person["streak"], 11)
        reconcile(person, date(2026, 10, 23))  # Thursday now expired
        self.assertEqual(person["streak"], 0)

    def test_freeze_maintains_streak_and_speaking_counts_once(self):
        person = new_person("Debater", list(range(7)), date(2026, 10, 25), 227)
        record(person, date(2026, 10, 25), "frozen")
        record(person, date(2026, 10, 25), "frozen")
        self.assertEqual(person["freeze_count"], 1)
        self.assertEqual(person["streak"], 227)
        reconcile(person, date(2026, 10, 26))
        record(person, date(2026, 10, 26), "frozen")
        record(person, date(2026, 10, 26), "yes")
        record(person, date(2026, 10, 26), "yes")
        self.assertEqual(person["streak"], 228)

    def test_unscheduled_reactions_do_not_change_streak(self):
        person = new_person("Debater", [1], date(2026, 10, 21), 7)
        record(person, date(2026, 10, 21), "yes")
        record(person, date(2026, 10, 21), "frozen")
        self.assertEqual((person["streak"], person["freeze_count"]), (7, 0))

    def test_pause_and_restart_catchup(self):
        person = new_person("Debater", [], date(2026, 10, 20), 20)
        reconcile(person, date(2026, 11, 1))
        self.assertEqual(person["streak"], 20)
        person["schedule"] = list(range(7))
        reconcile(person, date(2026, 11, 3))
        self.assertEqual(person["streak"], 0)

    def test_milestone_only_on_exact_new_credit(self):
        person = new_person("Debater", list(range(7)), date(2026, 10, 20), 9)
        self.assertTrue(record(person, date(2026, 10, 20), "yes")[1])
        self.assertFalse(record(person, date(2026, 10, 20), "yes")[1])
        self.assertFalse(record(person, date(2026, 10, 21), "yes")[1])

    def test_schedule_parsing(self):
        self.assertEqual(parse_schedule("Tuesday, thu tuesday"), [1, 3])
        self.assertEqual(parse_schedule("daily"), list(range(7)))
        self.assertEqual(parse_schedule("off"), [])
        for text in ("", "monkey", "mon off"):
            with self.assertRaises(ValueError):
                parse_schedule(text)

    def test_zero_streaks_hidden_not_deleted(self):
        data = bot._default_data()
        data["participants"]["1"] = new_person("Hidden", [1], date(2026, 10, 20))
        data["participants"]["2"] = new_person("Visible", [1], date(2026, 10, 20), 7)
        data["legacy_scores"]["LegacyZero"] = {"streak": 0}
        text = bot.format_leaderboard(data)
        self.assertIn("Visible", text)
        self.assertNotIn("Hidden", text)
        self.assertNotIn("LegacyZero", text)
        self.assertIn("1", data["participants"])


class DiscordFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = patch.multiple(
            bot, _state=bot._default_data(), _state_message=Mock(),
            _state_revision=0, _saved_revision=0, _action_lock=asyncio.Lock(),
        )
        self.state.start()
        self.addCleanup(self.state.stop)
        self.clock = patch.object(bot, "today_pt", return_value=date(2026, 10, 20))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.member = Mock(id=5, display_name="Debater", mention="<@5>")
        self.channel = Mock(send=AsyncMock())

    async def test_schedule_is_self_service_and_claims_baseline(self):
        data = bot.load_data()
        data["legacy_scores"]["Debater"] = {"streak": 227, "date": "2026-10-19"}
        bot.save_data(data)
        with patch.object(bot, "persist_discord_state", AsyncMock()):
            await bot.set_schedule(self.member, "tue thu", self.channel)
        person = bot.load_data()["participants"]["5"]
        self.assertEqual((person["schedule"], person["streak"]), ([1, 3], 227))
        self.assertNotIn("Debater", bot.load_data()["legacy_scores"])

    async def test_mention_schedule_and_help_commands(self):
        client = Mock(user=Mock(id=99))
        client.user.mentioned_in.return_value = True
        message = Mock(author=self.member, guild=Mock(), channel=self.channel,
                       mention_everyone=False, content="<@99> schedule mon, wed, fri")
        self.member.bot = False
        self.channel.id = bot.CHANNEL_ID
        with patch.object(bot, "bot", client), \
                patch.object(bot, "persist_discord_state", AsyncMock()):
            await bot.on_message(message)
            self.assertEqual(bot.load_data()["participants"]["5"]["schedule"], [0, 2, 4])
            message.content = "<@!99> help"
            await bot.on_message(message)
        help_text = self.channel.send.call_args.args[0]
        self.assertIn("@Squolingo schedule daily", help_text)
        self.assertIn("Pacific time", help_text)
        self.assertIn("@Squolingo freeze", help_text)

    async def test_both_reminders_have_both_reactions_and_track_date(self):
        messages = [Mock(add_reaction=AsyncMock(), id=10),
                    Mock(add_reaction=AsyncMock(), id=20)]
        self.channel.send.side_effect = messages
        with patch.object(bot, "persist_discord_state", AsyncMock()), \
                patch.object(bot, "bot", Mock(get_channel=Mock(return_value=self.channel))):
            await bot.send_morning_reminder()
            await bot.send_evening_reminder()
        for message in messages:
            self.assertEqual([call.args[0] for call in message.add_reaction.await_args_list],
                             ["🔥", "🧊"])
        self.assertEqual(bot.load_data()["morning_messages"][0]["date"], "2026-10-20")
        for call in self.channel.send.call_args_list:
            self.assertNotIn("notion", call.args[0].lower())

    async def test_speaking_edits_reminders_without_removing_reactions(self):
        data = bot.load_data()
        data["participants"]["5"] = new_person("Debater", [1], date(2026, 10, 20), 9)
        data["morning_messages"] = [{"id": 10, "date": "2026-10-20"}]
        bot.save_data(data)
        reminder = Mock(edit=AsyncMock(), remove_reaction=AsyncMock())
        self.channel.fetch_message = AsyncMock(return_value=reminder)
        with patch.object(bot, "persist_discord_state", AsyncMock()):
            await bot.handle_action(self.member, "yes", self.channel)
            await bot.handle_action(self.member, "yes", self.channel)
        self.assertEqual(bot.load_data()["participants"]["5"]["streak"], 10)
        reminder.edit.assert_awaited()
        reminder.remove_reaction.assert_not_awaited()
        congratulations = [call for call in self.channel.send.call_args_list
                           if "Congrats" in call.args[0]]
        self.assertEqual(len(congratulations), 1)

    async def test_old_reminder_reaction_cannot_backdate_speaking(self):
        data = bot.load_data()
        data["morning_messages"] = [{"id": 10, "date": "2026-10-19"}]
        bot.save_data(data)
        self.member.bot = False
        payload = Mock(member=self.member, channel_id=bot.CHANNEL_ID,
                       message_id=10, emoji="🔥")
        with patch.object(bot, "bot", Mock(get_channel=Mock(return_value=self.channel))), \
                patch.object(bot, "handle_action", AsyncMock()) as action:
            await bot.on_raw_reaction_add(payload)
        action.assert_not_awaited()

    async def test_both_emoji_actions_route_on_either_reminder(self):
        data = bot.load_data()
        data["morning_messages"] = [{"id": 10, "date": "2026-10-20"}]
        data["evening_messages"] = [{"id": 20, "date": "2026-10-20"}]
        bot.save_data(data)
        self.member.bot = False
        with patch.object(bot, "bot", Mock(get_channel=Mock(return_value=self.channel))), \
                patch.object(bot, "handle_action", AsyncMock()) as action:
            for message_id in (10, 20):
                for emoji, expected in (("🔥", "yes"), ("🧊", "frozen")):
                    payload = Mock(member=self.member, channel_id=bot.CHANNEL_ID,
                                   message_id=message_id, emoji=emoji)
                    await bot.on_raw_reaction_add(payload)
                    action.assert_awaited_with(self.member, expected,
                                               self.channel, "2026-10-20")

    async def test_reaction_waiting_across_midnight_is_not_credited_to_new_day(self):
        with patch.object(bot, "persist_discord_state", AsyncMock()) as persist:
            await bot.handle_action(self.member, "yes", self.channel, "2026-10-19")
        persist.assert_not_awaited()
        self.assertEqual(bot.load_data()["participants"], {})


if __name__ == "__main__":
    unittest.main()
