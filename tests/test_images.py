from io import BytesIO
from queue import Queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from chatbot_core import asset_url, avatar_url
from desktop_images import ImageCache


class ImageTests(unittest.TestCase):
    def test_connect_and_reconnect_deliver_images_to_current_ui_queue(self):
        import tkinter as tk
        import app
        root = tk.Tk()
        root.withdraw()
        with patch.object(app, 'load_token', return_value=''):
            application = app.App(root)
        try:
            for _ in range(2):
                application.connect_button.configure(state='normal')
                previous = application.events
                application.token.insert(0, 'offline-test-token')
                with patch.object(app.threading.Thread, 'start'):
                    application.connect()
                self.assertIsNot(application.events, previous)
                key = ('https://cdn.discordapp.com/avatar.png', 32, True)
                with patch('desktop_images.urlopen', side_effect=OSError):
                    application.images.download(key)
                self.assertEqual(application.events.get_nowait(), ('image_loaded', key, None))
                self.assertTrue(previous.empty())
        finally:
            application.images.close()
            root.destroy()

    def test_asset_static_size_and_server_profile_precedence(self):
        asset = Mock()
        asset.with_format.return_value.with_size.return_value = 'https://cdn.discordapp.com/avatar.png'
        self.assertEqual(asset_url(asset), 'https://cdn.discordapp.com/avatar.png')
        asset.with_format.assert_called_once_with('png')
        asset.with_format.return_value.with_size.assert_called_once_with(64)
        user = SimpleNamespace(id=2, display_avatar=asset)
        self.assertEqual(avatar_url(user, SimpleNamespace(id=1), {(1, 2): 'server'}), 'server')
        self.assertEqual(avatar_url(user, SimpleNamespace(id=3), {(1, 2): 'server'}), 'https://cdn.discordapp.com/avatar.png')
        self.assertEqual(asset_url(None), '')

    def test_pending_requests_deduplicated_and_other_hosts_ignored(self):
        cache = ImageCache(Queue())
        try:
            with patch.object(cache.pool, 'submit') as submit:
                cache.get('https://cdn.discordapp.com/avatar.png', 32)
                cache.get('https://cdn.discordapp.com/avatar.png', 32)
                cache.get('https://example.com/avatar.png', 32)
                self.assertEqual(submit.call_count, 1)
        finally:
            cache.close()

    def test_download_masks_and_failure_retry(self):
        cache = ImageCache(Queue())
        raw = BytesIO(); Image.new('RGB', (64, 64), 'red').save(raw, format='PNG')
        key = ('https://cdn.discordapp.com/avatar.png', 32, True)
        try:
            with patch('desktop_images.urlopen', return_value=BytesIO(raw.getvalue())):
                cache.download(key)
            kind, result_key, result = cache.events.get_nowait()
            self.assertEqual((kind, result_key, result.size), ('image_loaded', key, (32, 32)))
            self.assertEqual(result.getpixel((0, 0))[3], 0)
            self.assertEqual(result.getpixel((16, 16))[3], 255)
            with patch('desktop_images.urlopen', side_effect=OSError):
                cache.download(key)
            self.assertIsNone(cache.events.get_nowait()[2])
            cache.finish(key, None)
            with patch.object(cache.pool, 'submit') as submit:
                cache.get(*key)
                submit.assert_not_called()
        finally:
            cache.close()
