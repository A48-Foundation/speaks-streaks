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
            _fire_emojis_initialized=False,
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

    async def test_both_reminders_use_buttons_without_adding_reactions(self):
        messages = [Mock(add_reaction=AsyncMock(), id=10),
                    Mock(add_reaction=AsyncMock(), id=20)]
        self.channel.send.side_effect = messages
        with patch.object(bot, "persist_discord_state", AsyncMock()), \
                patch.object(bot, "bot", Mock(get_channel=Mock(return_value=self.channel))):
            await bot.send_morning_reminder()
            await bot.send_evening_reminder()
        for message in messages:
            message.add_reaction.assert_not_awaited()
        self.assertEqual(bot.load_data()["morning_messages"][0]["date"], "2026-10-20")
        for call in self.channel.send.call_args_list:
            self.assertNotIn("notion", call.args[0].lower())
            self.assertNotIn("react with", call.args[0].lower())
            self.assertTrue(call.kwargs["view"].is_persistent())

    async def test_race_cards_attach_real_streaks_and_refresh_replaces_old_images(self):
        data = bot.load_data()
        data["participants"]["5"] = new_person("Debater", [1], date(2026, 10, 20), 61)
        data["morning_messages"] = [{"id": 10, "date": "2026-10-20"}]
        bot.save_data(data)
        reminder = Mock(edit=AsyncMock(), reactions=[])
        self.channel.send.return_value = Mock(id=20)
        self.channel.fetch_message = AsyncMock(return_value=reminder)
        with patch.object(bot, "race_attachments", return_value=[b"GIF89a"]) as render, \
                patch.object(bot, "persist_discord_state", AsyncMock()), \
                patch.object(bot, "bot", Mock(get_channel=Mock(return_value=self.channel))):
            await bot.send_evening_reminder()
            await bot.refresh_reminders(self.channel, data)
        render.assert_called_with(data, date(2026, 10, 20))
        sent = self.channel.send.call_args.kwargs
        self.assertEqual(sent["files"][0].filename, "shark-race-1.gif")
        self.assertEqual(sent["embeds"], [])
        edited = reminder.edit.call_args.kwargs
        self.assertEqual(edited["embeds"], [])
        self.assertEqual(len(edited["attachments"]), 1)
        self.assertIsNot(sent["files"][0], edited["attachments"][0])

    async def test_race_render_failure_retains_text_scores_and_buttons(self):
        data = bot.load_data()
        data["legacy_scores"] = {"Debater": {"streak": 61}}
        with patch.object(bot, "race_attachments", side_effect=OSError("Missing font")):
            with self.assertLogs("squolingo", level="ERROR"):
                embeds, images = await bot.reminder_cards(data, date(2026, 10, 20))
        self.assertEqual(images, [])
        self.assertIn("Debater", embeds[0].fields[0].name)

    async def test_all_report_commands_show_shark_race_attachments(self):
        data = bot.load_data()
        data["legacy_scores"] = {"Debater": {"streak": 61}}
        bot.save_data(data)
        with patch.object(bot, "race_attachments", return_value=[b"GIF89a"]), \
                patch.object(bot, "persist_discord_state", AsyncMock()):
            for command in ("streaks", "report scores", "report streaks",
                            "check streak calculations"):
                await bot.dispatch(self.member, command, self.channel)
        self.assertEqual(self.channel.send.await_count, 4)
        for call in self.channel.send.call_args_list:
            self.assertEqual(call.kwargs["files"][0].filename, "shark-race-1.gif")
            self.assertEqual(call.kwargs["embeds"], [])

    async def test_speaking_edits_reminders_without_removing_reactions(self):
        data = bot.load_data()
        data["participants"]["5"] = new_person("Debater", [1], date(2026, 10, 20), 9)
        data["morning_messages"] = [{"id": 10, "date": "2026-10-20"}]
        bot.save_data(data)
        reminder = Mock(edit=AsyncMock(), remove_reaction=AsyncMock(), reactions=[])
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
                patch.object(bot, "ensure_fire_emojis", AsyncMock()), \
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

    async def test_colored_flames_reuse_existing_emoji_and_create_missing_once(self):
        red = bot.discord.PartialEmoji(name=bot.FIRE_EMOJI_PREFIX + "red", id=1)
        created = []
        async def create(name, image):
            self.assertTrue(image.startswith(b"\x89PNG"))
            emoji = bot.discord.PartialEmoji(name=name, id=len(created) + 2)
            created.append(emoji)
            return emoji
        client = Mock(fetch_application_emojis=AsyncMock(return_value=[red]),
                      create_application_emoji=AsyncMock(side_effect=create))
        with patch.dict(bot.FIRE_EMOJIS, {}, clear=True), patch.object(bot, "bot", client):
            await bot.ensure_fire_emojis()
            await bot.ensure_fire_emojis()
            self.assertEqual(len(bot.FIRE_EMOJIS), 3)
            self.assertIn(bot.FIRE_EMOJI_PREFIX + "blue", bot.FIRE_EMOJIS["blue"])
            self.assertEqual(bot.FIRE_EMOJIS["red"], str(red))
        client.fetch_application_emojis.assert_awaited_once()
        self.assertEqual(client.create_application_emoji.await_count, 2)

    async def test_failed_emoji_setup_keeps_labeled_fallback_available(self):
        error = bot.discord.Forbidden(Mock(status=403, reason="Forbidden"), "Denied")
        client = Mock(fetch_application_emojis=AsyncMock(side_effect=error))
        with patch.dict(bot.FIRE_EMOJIS, {}, clear=True), patch.object(bot, "bot", client):
            with self.assertLogs("squolingo", level="ERROR"):
                await bot.ensure_fire_emojis()
            self.assertEqual(bot.flame_badge(500), "🔥 Blue fire")
            self.assertFalse(bot._fire_emojis_initialized)

    async def test_repeat_spoke_button_cannot_double_credit(self):
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
            await view.children[0].callback(interaction)
        self.assertEqual(bot.load_data()["participants"]["5"]["streak"], 8)
        self.assertEqual(interaction.response.defer.await_count, 2)

    async def test_existing_reminder_reactions_are_cleared(self):
        message = Mock(reactions=[Mock(me=True)], clear_reactions=AsyncMock())
        await bot.clear_reminder_reactions(message)
        message.clear_reactions.assert_awaited_once()

    async def test_missing_manage_messages_removes_bot_reactions_only(self):
        error = bot.discord.Forbidden(Mock(status=403, reason="Forbidden"), "Denied")
        message = Mock(reactions=[Mock(me=True, emoji="🔥"), Mock(me=False, emoji="🧊")],
                       clear_reactions=AsyncMock(side_effect=error),
                       remove_reaction=AsyncMock())
        client = Mock(user=Mock())
        with patch.object(bot, "bot", client):
            with self.assertLogs("squolingo", level="WARNING"):
                await bot.clear_reminder_reactions(message)
        message.remove_reaction.assert_awaited_once_with("🔥", client.user)

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
        interaction = Mock(user=self.member, response=Mock(defer=AsyncMock()),
                           followup=Mock(send=AsyncMock()))
        await bot.ReminderView().children[3].callback(interaction)
        result = interaction.followup.send.call_args.kwargs
        self.assertIsInstance(result["view"], bot.ProfileView)
        self.assertIn("Tue 20", result["embed"].description)
        self.assertTrue(result["ephemeral"])

    async def test_profile_button_saves_only_own_appearance_and_preserves_records(self):
        data = bot.load_data()
        person = new_person("Debater", [1], date(2026, 10, 20), 61)
        person["results"]["2026-10-20"] = "frozen"
        data["participants"]["5"] = person
        bot.save_data(data)
        interaction = Mock(user=self.member, channel=self.channel, channel_id=bot.CHANNEL_ID,
                           response=Mock(defer=AsyncMock()), edit_original_response=AsyncMock(),
                           followup=Mock(send=AsyncMock()))
        await bot.ReminderView().children[3].callback(interaction)
        view = interaction.followup.send.call_args.kwargs["view"]
        view.selected_color = "#ff729e"
        view.selected_kind = "hammerhead"
        with patch.object(bot, "persist_discord_state", AsyncMock()) as persist, \
                patch.object(bot, "refresh_reminders", AsyncMock()):
            await view.save.callback(interaction)
        saved = bot.load_data()["participants"]["5"]
        self.assertEqual(saved, dict(person, shark_color="#ff729e", shark_type="hammerhead"))
        persist.assert_awaited_once()
        self.channel.send.assert_not_awaited()
        self.assertTrue(interaction.followup.send.call_args.kwargs["ephemeral"])

    async def test_profile_registration_claims_legacy_without_setting_schedule(self):
        data = bot.load_data()
        data["legacy_scores"] = {"Debater": {"streak": 232}}
        bot.save_data(data)
        view = bot.ProfileView(self.member, None)
        view.selected_color = "#28e1ef"
        view.selected_kind = "whale"
        interaction = Mock(user=self.member, channel=self.channel, channel_id=bot.CHANNEL_ID,
                           response=Mock(defer=AsyncMock()), edit_original_response=AsyncMock())
        with patch.object(bot, "persist_discord_state", AsyncMock()), \
                patch.object(bot, "refresh_reminders", AsyncMock()):
            await view.save.callback(interaction)
        person = bot.load_data()["participants"]["5"]
        self.assertEqual((person["streak"], person["schedule"]), (232, []))
        self.assertNotIn("Debater", bot.load_data()["legacy_scores"])

    async def test_profile_preview_rejects_another_user_without_changing_state(self):
        view = bot.ProfileView(self.member, None)
        interaction = Mock(user=Mock(id=6), channel_id=bot.CHANNEL_ID,
                           response=Mock(send_message=AsyncMock()))
        before = bot.load_data()
        await view.save.callback(interaction)
        self.assertEqual(bot.load_data(), before)
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_dropdown_updates_preview_in_place_without_saving(self):
        view = bot.ProfileView(self.member, None)
        view.color._values = ["#ff729e"]
        view.kind._values = ["hammerhead"]
        interaction = Mock(user=self.member, channel_id=bot.CHANNEL_ID,
                           response=Mock(defer=AsyncMock()), edit_original_response=AsyncMock())
        before = bot.load_data()
        await view.change_color(interaction)
        first_image = interaction.edit_original_response.call_args.kwargs["attachments"][0].fp.getvalue()
        await view.change_kind(interaction)
        updated = interaction.edit_original_response.call_args.kwargs
        self.assertNotEqual(first_image, updated["attachments"][0].fp.getvalue())
        self.assertEqual(updated["embed"].image.url, "attachment://shark-profile.png")
        self.assertEqual((view.selected_color, view.selected_kind), ("#ff729e", "hammerhead"))
        self.assertEqual(bot.load_data(), before)
        self.assertEqual(interaction.edit_original_response.await_count, 2)
        self.channel.send.assert_not_awaited()

    async def test_schedule_freeze_and_speak_do_not_post_channel_confirmations(self):
        with patch.object(bot, "persist_discord_state", AsyncMock()), \
                patch.object(bot, "refresh_reminders", AsyncMock()):
            await bot.set_schedule(self.member, "tue", self.channel)
            await bot.handle_action(self.member, "frozen", self.channel)
            await bot.handle_action(self.member, "yes", self.channel)
            await bot.handle_action(self.member, "yes", self.channel)
        self.assertEqual(bot.load_data()["participants"]["5"]["streak"], 1)
        self.channel.send.assert_not_awaited()

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
