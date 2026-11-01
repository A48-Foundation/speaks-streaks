import asyncio
import unittest
from datetime import date
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

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
        text = str(bot.leaderboard_embed(data, date(2026, 10, 20)).to_dict())
        self.assertIn("Visible", text)
        self.assertNotIn("Hidden", text)
        self.assertNotIn("LegacyZero", text)
        self.assertIn("1", data["participants"])

    def test_october_recovery_repairs_legacy_totals_once(self):
        data = bot._default_data()
        data["legacy_scores"] = {
            "aanya": {"streak": 5}, "Ethan": {"streak": 0}, "Julia Ye": {"streak": 1},
        }
        self.assertTrue(bot.recover_october_totals(data, date(2026, 11, 1)))
        self.assertEqual({name: value["streak"] for name, value in data["legacy_scores"].items()},
                         {"aanya": 232, "Ethan": 15, "Julia Ye": 61})
        data["legacy_scores"]["aanya"]["streak"] = 233
        self.assertFalse(bot.recover_october_totals(data, date(2026, 11, 1)))
        self.assertEqual(data["legacy_scores"]["aanya"]["streak"], 233)

    def test_recovery_preserves_current_day_credit_freeze_and_schedule(self):
        data = bot._default_data()
        today = date(2026, 11, 1)
        for user_id, name, result in (("1", "aanya", "yes"),
                                     ("2", "Ethan", "frozen"),
                                     ("3", "Julia Ye", None)):
            person = new_person(name, [6], today, 5)
            if result:
                person["results"][today.isoformat()] = result
            data["participants"][user_id] = person
        self.assertTrue(bot.recover_october_totals(data, today))
        self.assertEqual([p["streak"] for p in data["participants"].values()], [233, 15, 61])
        self.assertEqual(data["participants"]["2"]["results"][today.isoformat()], "frozen")
        self.assertEqual(data["participants"]["1"]["schedule"], [6])
        record(data["participants"]["1"], today, "yes")
        self.assertEqual(data["participants"]["1"]["streak"], 233)

    def test_historical_recovery_does_not_override_later_resets(self):
        data = bot._default_data()
        data["participants"]["1"] = new_person("aanya", [6], date(2026, 11, 2), 0)
        self.assertFalse(bot.recover_october_totals(data, date(2026, 11, 2)))
        self.assertEqual(data["participants"]["1"]["streak"], 0)


class DiscordFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = patch.multiple(
            bot, _state=bot._default_data(), _state_message=Mock(),
            _state_revision=0, _saved_revision=0, _action_lock=asyncio.Lock(),
            _view_registered=False,
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

    async def test_repair_requires_manage_server_permission(self):
        self.member.guild_permissions = SimpleNamespace(administrator=False, manage_guild=False)
        before = bot.load_data()
        with patch.object(bot, "persist_discord_state", AsyncMock()) as persist:
            await bot.repair_total(self.member, "<@5> 232", self.channel)
        self.assertEqual(bot.load_data(), before)
        persist.assert_not_awaited()

    async def test_repair_preserves_schedule_and_already_recorded_speaking(self):
        self.member.bot = False
        self.member.guild_permissions = SimpleNamespace(administrator=False, manage_guild=True)
        self.member.guild = Mock(get_member=Mock(return_value=self.member))
        data = bot.load_data()
        person = new_person("Debater", [1, 3], date(2026, 10, 20), 5)
        person["results"]["2026-10-20"] = "yes"
        data["participants"]["5"] = person
        bot.save_data(data)
        with patch.object(bot, "persist_discord_state", AsyncMock()) as persist:
            await bot.repair_total(self.member, "<@5> 232", self.channel)
            await bot.handle_action(self.member, "yes", self.channel)
        state = bot.load_data()
        self.assertEqual(state["participants"]["5"]["streak"], 232)
        self.assertEqual(state["participants"]["5"]["schedule"], [1, 3])
        self.assertEqual(state["repairs"][0]["previous"], 5)
        self.assertEqual(state["repairs"][0]["total"], 232)
        persist.assert_awaited()

    async def test_repair_claims_legacy_entry_without_guessing_schedule(self):
        self.member.bot = False
        self.member.guild_permissions = SimpleNamespace(administrator=True, manage_guild=True)
        self.member.guild = Mock(get_member=Mock(return_value=self.member))
        data = bot.load_data()
        data["legacy_scores"]["Debater"] = {"streak": 5}
        bot.save_data(data)
        with patch.object(bot, "persist_discord_state", AsyncMock()):
            await bot.repair_total(self.member, "<@5> 232", self.channel)
        state = bot.load_data()
        self.assertNotIn("Debater", state["legacy_scores"])
        self.assertEqual(state["participants"]["5"]["streak"], 232)
        self.assertEqual(state["participants"]["5"]["schedule"], [])

    async def test_startup_applies_and_persists_assumed_recovery_only_once(self):
        data = bot.load_data()
        data["legacy_scores"] = {"aanya": {"streak": 5}, "Ethan": {"streak": 0},
                                 "Julia Ye": {"streak": 1}}
        data["morning_messages"] = [{"id": 10, "date": "2026-11-01"}]
        bot.save_data(data)
        loops = {name: Mock(is_running=Mock(return_value=True)) for name in
                 ("morning_task", "evening_task", "midnight_task",
                  "reconcile_task", "persist_state_task")}
        clock = Mock()
        clock.now.return_value = bot.datetime(2026, 11, 1, 13, tzinfo=bot.PT)
        client = Mock(get_channel=Mock(return_value=self.channel))
        with patch.multiple(bot, **loops), patch.object(bot, "datetime", clock), \
                patch.object(bot, "today_pt", return_value=date(2026, 11, 1)), \
                patch.object(bot, "bot", client), \
                patch.object(bot, "persist_discord_state", AsyncMock()) as persist, \
                patch.object(bot, "refresh_reminders", AsyncMock()):
            await bot.on_ready()
            await bot.on_ready()
        persist.assert_awaited()
        self.assertEqual(bot.load_data()["legacy_scores"]["Ethan"]["streak"], 15)
        notices = [call for call in self.channel.send.call_args_list
                   if "recovery applied" in call.args[0]]
        self.assertEqual(len(notices), 1)
        client.add_view.assert_called_once()
        self.assertTrue(client.add_view.call_args.args[0].is_persistent())

    async def test_spoke_button_and_fire_reaction_cannot_double_credit(self):
        data = bot.load_data()
        data["participants"]["5"] = new_person("Debater", [1], date(2026, 10, 20), 7)
        data["morning_messages"] = [{"id": 10, "date": "2026-10-20"}]
        bot.save_data(data)
        view = bot.ReminderView()
        interaction = Mock(user=self.member, channel=self.channel, message=Mock(id=10),
                           response=Mock(defer=AsyncMock()),
                           followup=Mock(send=AsyncMock()))
        with patch.object(bot, "persist_discord_state", AsyncMock()), \
                patch.object(bot, "refresh_reminders", AsyncMock()):
            await view.children[0].callback(interaction)
            await bot.handle_action(self.member, "yes", self.channel, "2026-10-20")
        self.assertEqual(bot.load_data()["participants"]["5"]["streak"], 8)
        interaction.response.defer.assert_awaited_with(ephemeral=True)

    async def test_old_reminder_button_cannot_record_today(self):
        data = bot.load_data()
        data["morning_messages"] = [{"id": 10, "date": "2026-10-19"}]
        bot.save_data(data)
        interaction = Mock(user=self.member, channel=self.channel, message=Mock(id=10),
                           response=Mock(send_message=AsyncMock()))
        with patch.object(bot, "handle_action", AsyncMock()) as action:
            await bot.ReminderView().children[0].callback(interaction)
        action.assert_not_awaited()
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_schedule_button_opens_own_schedule_modal(self):
        data = bot.load_data()
        data["participants"]["5"] = new_person("Debater", [1, 3], date(2026, 10, 20))
        bot.save_data(data)
        interaction = Mock(user=self.member, response=Mock(send_modal=AsyncMock()))
        await bot.ReminderView().children[2].callback(interaction)
        modal = interaction.response.send_modal.call_args.args[0]
        self.assertEqual(modal.frequency.default, "tue, thu")

    async def test_week_button_is_private(self):
        data = bot.load_data()
        data["participants"]["5"] = new_person("Debater", [1], date(2026, 10, 20), 7)
        bot.save_data(data)
        interaction = Mock(user=self.member, response=Mock(send_message=AsyncMock()))
        await bot.ReminderView().children[3].callback(interaction)
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])
        self.assertIn("Your speaking week",
                      interaction.response.send_message.call_args.kwargs["embed"].title)

    async def test_major_milestone_sends_one_animation_not_on_repeat(self):
        data = bot.load_data()
        data["participants"]["5"] = new_person("Debater", [1], date(2026, 10, 20), 49)
        bot.save_data(data)
        with patch.object(bot, "persist_discord_state", AsyncMock()), \
                patch.object(bot, "refresh_reminders", AsyncMock()):
            await bot.handle_action(self.member, "yes", self.channel)
            await bot.handle_action(self.member, "yes", self.channel)
        animated = [call for call in self.channel.send.call_args_list if "file" in call.kwargs]
        self.assertEqual(len(animated), 1)
        self.assertEqual(animated[0].kwargs["embed"].image.url, "attachment://milestone.gif")


if __name__ == "__main__":
    unittest.main()
