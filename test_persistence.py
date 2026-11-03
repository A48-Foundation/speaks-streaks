import asyncio
import json
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

with patch.dict(os.environ, {
    "DISCORD_TOKEN": "test", "CHANNEL_ID": "1", "LOCKED_IN_ROLE_ID": "2",
}):
    import bot


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = patch.multiple(
            bot, _state=None, _state_message=None, _state_revision=0,
            _saved_revision=-1, _state_lock=asyncio.Lock(), _action_lock=asyncio.Lock(),
        )
        self.state.start()
        self.addCleanup(self.state.stop)
        self.message = Mock(author=Mock(id=1), content=bot.STATE_MARKER,
                            created_at=datetime(2026, 10, 26, tzinfo=bot.PT))
        self.message.edit = AsyncMock()
        self.channel = Mock(send=AsyncMock(return_value=self.message))

    async def test_new_freeze_survives_restart_without_local_files(self):
        uploaded = []
        async def send(content, file):
            uploaded.append(file.fp.read())
            return self.message
        self.channel.send.side_effect = send
        data = bot._default_data()
        data["participants"]["5"] = bot.new_person(
            "Debater", [1, 3], datetime(2026, 10, 25).date(), 227
        )
        data["participants"]["5"].update(shark_color="#ff729e", shark_type="hammerhead")
        bot.save_data(data)
        bot.save_frozen_dates({"debater": {"2026-10-25"}})
        await bot.persist_discord_state(self.channel)
        self.message.attachments = [Mock(read=AsyncMock(return_value=uploaded[0]))]
        async def history(**kwargs):
            yield self.message
        self.channel.history = history
        bot._state = None
        bot._state_message = None
        with patch.object(bot, "bot", Mock(user=Mock(id=1))):
            await bot.restore_discord_state(self.channel)
        self.assertEqual(bot.load_frozen_dates(), {"debater": {"2026-10-25"}})
        self.assertEqual(bot.load_data()["participants"]["5"]["schedule"], [1, 3])
        self.assertEqual(bot.load_data()["participants"]["5"]["streak"], 227)
        self.assertEqual(bot.load_data()["participants"]["5"]["shark_type"], "hammerhead")
        self.assertEqual(bot.load_data()["participants"]["5"]["shark_color"], "#ff729e")
        bot.save_frozen_dates({"debater": {"2026-10-25", "2026-10-30"}})
        await bot.persist_discord_state(self.channel)
        self.message.edit.assert_awaited_once()

    async def test_failed_save_is_retried(self):
        bot.save_data(bot._default_data())
        self.channel.send.side_effect = RuntimeError("Discord unavailable")
        with self.assertRaises(RuntimeError):
            await bot.persist_discord_state(self.channel)
        self.assertNotEqual(bot._saved_revision, bot._state_revision)
        self.channel.send.side_effect = None
        await bot.persist_discord_state(self.channel)
        self.assertEqual(bot._saved_revision, bot._state_revision)

    async def test_corrupt_discord_state_does_not_silently_reset(self):
        self.message.attachments = [Mock(read=AsyncMock(return_value=b"{"))]
        async def history(**kwargs):
            yield self.message
        self.channel.history = history
        with patch.object(bot, "bot", Mock(user=Mock(id=1))):
            with self.assertRaises(json.JSONDecodeError):
                await bot.restore_discord_state(self.channel)
        self.channel.send.assert_not_awaited()

    async def test_old_discord_state_and_leaderboard_migrate_without_notion(self):
        payload = {"frozen_dates": {"aanya": ["2026-10-25"]},
                   "freeze_counts": {"aanya": 9}}
        self.message.attachments = [Mock(read=AsyncMock(return_value=json.dumps(payload).encode()))]
        reminder = Mock(author=Mock(id=1),
                        content="Current Streaks:\n```\naanya 🔥🔥    227\nEthan    0\n```",
                        created_at=datetime(2026, 10, 25, 21, tzinfo=bot.PT))
        async def history(**kwargs):
            yield self.message
            yield reminder
        self.channel.history = history
        with patch.object(bot, "bot", Mock(user=Mock(id=1))), \
                patch.object(bot, "today_pt", return_value=datetime(2026, 10, 26).date()):
            await bot.restore_discord_state(self.channel)
        data = bot.load_data()
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["legacy_scores"]["aanya"]["streak"], 227)
        self.assertEqual(data["legacy_freeze_counts"]["aanya"], 9)
        self.message.edit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
