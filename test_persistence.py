import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

with patch.dict(os.environ, {
    "DISCORD_TOKEN": "test", "CHANNEL_ID": "1", "LOCKED_IN_ROLE_ID": "2",
    "NOTION_LINK": "test", "NOTION_TOKEN": "test", "DATABASE_ID": "test",
}):
    import bot


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = self.directory.name
        self.paths = patch.multiple(
            bot, APP_DIR=root, BOT_DATA_FILE=os.path.join(root, "bot_data.json"),
            FROZEN_DATES_FILE=os.path.join(root, "frozen_dates.json"),
            _state=None, _state_message=None, _state_revision=0,
            _saved_revision=-1, _state_lock=asyncio.Lock(),
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.addCleanup(self.directory.cleanup)
        self.message = Mock(author=Mock(id=1), content=bot.STATE_MARKER)
        self.message.edit = AsyncMock()
        self.channel = Mock(send=AsyncMock(return_value=self.message))

    async def test_new_freeze_survives_restart_without_local_files(self):
        uploaded = []
        async def send(content, file):
            uploaded.append(file.fp.read())
            return self.message
        self.channel.send.side_effect = send
        bot.save_data(bot._default_data())
        bot.save_frozen_dates({"debater": {"2026-10-25"}})
        await bot.persist_discord_state(self.channel)
        self.assertEqual(bot.load_frozen_dates(), {"debater": {"2026-10-25"}})
        self.message.attachments = [Mock(read=AsyncMock(return_value=uploaded[0]))]
        async def history(**kwargs):
            yield self.message
        self.channel.history = history
        bot._state = None
        bot._state_message = None
        with patch.object(bot, "bot", Mock(user=Mock(id=1))):
            await bot.restore_discord_state(self.channel)
        self.assertEqual(bot.load_frozen_dates(), {"debater": {"2026-10-25"}})
        self.assertFalse(os.path.exists(bot.BOT_DATA_FILE))
        self.assertFalse(os.path.exists(bot.FROZEN_DATES_FILE))
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

    async def test_missing_state_migrates_legacy_history(self):
        with open(bot.FROZEN_DATES_FILE, "w") as f:
            json.dump({"debater": ["2026-06-15"]}, f)
        with open(bot.BOT_DATA_FILE, "w") as f:
            json.dump({"frozen_dates": {"debater": ["2026-10-25"]}}, f)
        async def history(**kwargs):
            if False:
                yield
        self.channel.history = history
        await bot.restore_discord_state(self.channel)
        self.assertEqual(bot.load_frozen_dates()["debater"],
                         {"2026-06-15", "2026-10-25"})
        self.channel.send.assert_awaited_once()

    async def test_fresh_startup_never_rewrites_history(self):
        clock = Mock()
        clock.now.return_value = datetime(2026, 10, 26, 8, tzinfo=bot.PT)
        loops = {
            name: Mock(is_running=Mock(return_value=True))
            for name in ("morning_task", "evening_task", "midnight_task",
                         "poll_notion_changes", "persist_state_task")
        }
        async def history(**kwargs):
            if False:
                yield
        self.channel.history = history
        client = Mock(user=Mock(id=1), get_channel=Mock(return_value=self.channel))
        with patch.multiple(bot, **loops), patch.object(bot, "datetime", clock), \
                patch.object(bot, "bot", client), \
                patch.object(bot, "sync_all_streaks") as full_sync, \
                patch.object(bot, "process_previous_day") as previous_day:
            await bot.on_ready()
        full_sync.assert_not_called()
        previous_day.assert_not_called()


if __name__ == "__main__":
    unittest.main()
