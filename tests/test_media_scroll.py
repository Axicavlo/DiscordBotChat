import unittest
import time
from datetime import datetime, timezone
from types import SimpleNamespace as Row
from unittest.mock import patch
import tkinter as tk
import discord
from PIL import Image
import app



class MediaScrollTests(unittest.TestCase):
    def test_media_updates_preserve_reader_position_and_wheel_does_not_redraw(self):
        root = tk.Tk(); self.addCleanup(root.destroy)
        root.attributes('-alpha', 0); root.geometry('1100x720')
        with patch.object(app, 'load_token', return_value=''):
            application = app.App(root)
        self.addCleanup(application.images.close)
        application.connected = True; application.show_media = True
        application.bridge = Row(user=Row(id=7), member_names={}, member_avatars={})
        application.show_workspace(); application.empty.pack_forget()
        chat = app.Chat(application, 1, 'scroll'); application.chats[1] = chat
        self.addCleanup(chat.close)
        chat.window.pack(fill='both', expand=True)
        image_url = 'https://cdn.discordapp.com/test.png'
        embed = discord.Embed.from_dict({'image': {'url': image_url, 'width': 512, 'height': 512}})
        def row(ident, media=False):
            return Row(id=ident, author=Row(id=8, display_name='user'), guild=None, reference=None, mentions=[],
                content='text', clean_content='text', created_at=datetime.now(timezone.utc), edited_at=None,
                attachments=[], embeds=[embed] if media else [], stickers=[])
        chat.messages = {i: row(i, i in (1, 200)) for i in range(1, 201)}
        def pump(seconds=.25):
            end = time.monotonic()+seconds
            while time.monotonic() < end:
                root.update(); time.sleep(.01)
        with patch.object(application.images.pool, 'submit'):
            pump(); chat.render(); chat.scroll_messages('moveto', 1); pump()
            # Fill the pending thumbnail and settle layout before checking wheel-only work.
            for key in list(application.images.pending):
                application.images.finish(key, Image.new('RGBA', (220, 220), 'blue'))
            chat.render(); chat.scroll_messages('moveto', 1); pump()
            bottom = chat.view.canvasy(0)
            with patch.object(chat, 'render', wraps=chat.render) as redraw:
                chat.wheel_messages(Row(delta=120)); pump(.35)
                assert chat.view.canvasy(0) < bottom
                assert redraw.call_count == 0, redraw.call_count
            first_up = chat.view.canvasy(0)
            chat.render(); pump()
            assert abs(chat.view.canvasy(0)-first_up) <= 1
            # Image size changes above the viewport keep the same message and offset.
            chat.scroll_messages('moveto', .5); pump()
            top = chat.view.canvasy(0)
            anchor = next((mid, top-start) for mid, (start, end) in chat.message_positions.items() if end > top)
            for key in list(application.images.photos):
                application.images.finish(key, Image.new('RGBA', (40, 40), 'red'))
            chat.render(); pump()
            expected = chat.message_positions[anchor[0]][0] + anchor[1]
            assert abs(chat.view.canvasy(0)-expected) <= 1
            # New messages do not pull a reader down, but the exact bottom follows them.
            reading = chat.view.canvasy(0)
            chat.messages[201] = row(201); chat.render(); pump()
            assert abs(chat.view.canvasy(0)-reading) <= 1
            chat.scroll_messages('moveto', 1); chat.messages[202] = row(202); chat.render(); pump()
            assert chat.view.yview()[1] >= .999999
