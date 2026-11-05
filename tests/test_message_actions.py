import queue
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from chatbot_core import Bridge


class MessageActionsTests(unittest.IsolatedAsyncioTestCase):
    def bridge(self, author=7):
        message = SimpleNamespace(id=25, author=SimpleNamespace(id=author),
                                  edit=AsyncMock(), delete=AsyncMock())
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        bridge = SimpleNamespace(user=SimpleNamespace(id=7), events=queue.Queue(),
                                 get_channel=lambda cid: channel,
                                 prepare_member_names=AsyncMock())
        bridge.own_message = lambda cid, mid: Bridge.own_message(bridge, cid, mid)
        return bridge, message

    async def test_edit_own_message_publishes_updated_message_without_mentions(self):
        bridge, message = self.bridge()
        await Bridge.edit_text(bridge, 10, 25, '수정 내용')
        kwargs = message.edit.call_args.kwargs
        self.assertEqual(kwargs['content'], '수정 내용')
        self.assertEqual(kwargs['allowed_mentions'].to_dict(), {'parse': []})
        self.assertEqual(bridge.events.get_nowait(), ('message', 10, message.edit.return_value))
        self.assertEqual(bridge.events.get_nowait(), ('edited', 10, 25))

    async def test_other_authors_cannot_be_edited_or_deleted(self):
        bridge, message = self.bridge(author=8)
        with self.assertRaises(RuntimeError):
            await Bridge.edit_text(bridge, 10, 25, '수정')
        with self.assertRaises(RuntimeError):
            await Bridge.delete_message(bridge, 10, 25)
        message.edit.assert_not_awaited()
        message.delete.assert_not_awaited()

    async def test_invalid_edit_does_not_send_request(self):
        bridge, message = self.bridge()
        for text in ('   ', 'a' * 2001):
            with self.assertRaises(RuntimeError):
                await Bridge.edit_text(bridge, 10, 25, text)
        message.edit.assert_not_awaited()

    async def test_delete_updates_display_only_after_success(self):
        bridge, message = self.bridge()
        message.delete.side_effect = RuntimeError('실패')
        with self.assertRaises(RuntimeError):
            await Bridge.delete_message(bridge, 10, 25)
        self.assertTrue(bridge.events.empty())
        message.delete.side_effect = None
        await Bridge.delete_message(bridge, 10, 25)
        self.assertEqual(bridge.events.get_nowait(), ('deleted', 10, 25))
