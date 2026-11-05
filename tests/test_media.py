from io import BytesIO
from queue import Queue
from types import SimpleNamespace as Row
from unittest.mock import patch
import unittest
import discord
from PIL import Image
from chatbot_core.media import message_media, image_host, preview_layout
from desktop_images import ImageCache, Animation, decode_media


class MediaTests(unittest.TestCase):
    def test_animated_emoji_uses_gif_and_enlarged_emoji_uses_sticker_bounds(self):
        emoji = message_media(self.message(), '<a:dance:123>', True)['media'][0]
        self.assertIn('/123.gif?', emoji['url'])
        enlarged = message_media(self.message(), '[□](https://cdn.kamibot.app/e/test.webp)', True)['media']
        entries, _, _ = preview_layout(enlarged, 320, lambda key: None)
        self.assertEqual(enlarged[0]['kind'], 'enlarged_emoji')
        self.assertEqual(entries[0]['key'][1:], ((160, 160), 'sticker'))

    def test_gif_frames_and_timing_are_preserved(self):
        raw = BytesIO()
        frames = [Image.new('RGBA', (64, 64), color) for color in ('red', 'blue')]
        frames[0].save(raw, format='GIF', save_all=True, append_images=frames[1:], duration=[40, 80], loop=0)
        result = decode_media(raw.getvalue(), (32, 32), True)
        self.assertIsInstance(result, Animation)
        self.assertEqual(len(result.frames), 2)
        self.assertEqual(result.durations, [40, 80])
        cache = ImageCache(Queue())
        try:
            key = ('test', (32, 32), 'emoji')
            cache.animations[key] = (['red', 'blue'], [40, 80], 0, 10)
            self.assertEqual(cache.current(key, 10.01), 'red')
            self.assertEqual(cache.current(key, 10.05), 'blue')
            self.assertEqual(cache.current(key, 10.13), 'red')
        finally:
            cache.close()

    def test_original_404_retries_discord_proxy(self):
        from urllib.error import HTTPError
        original = 'https://cdn.kamibot.app/e/image.webp'
        proxy = 'https://images-ext-1.discordapp.net/external/hash/https/cdn.kamibot.app/e/image.webp'
        raw = BytesIO(); Image.new('RGB', (512, 512), 'red').save(raw, 'PNG')
        cache = ImageCache(Queue())
        key = (original, (160, 160), 'sticker')
        cache.alternatives[key] = (proxy,)
        try:
            with patch('desktop_images.urlopen', side_effect=[HTTPError(original, 404, 'missing', {}, None), BytesIO(raw.getvalue())]) as request:
                cache.download(key)
            self.assertEqual(cache.events.get_nowait()[2].size, (160, 160))
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args.args[0].full_url, proxy)
        finally:
            cache.close()

    def test_repeated_emoji_keep_count_and_pack_in_one_row(self):
        result = message_media(self.message(), '<:same:123>' * 5, True)
        self.assertEqual(len(result['media']), 5)
        entries, width, height = preview_layout(result['media'], 320, lambda key: None)
        self.assertEqual([entry['x'] for entry in entries], [0, 36, 72, 108, 144])
        self.assertEqual(height, 32)
        self.assertEqual(width, 176)

    def test_original_and_proxy_embed_represent_one_image(self):
        original = 'https://cdn.kamibot.app/e/sample.webp?ex=123'
        embed = discord.Embed.from_dict({'image': {'url': original,
            'proxy_url': 'https://images-ext-1.discordapp.net/external/hash/https/cdn.kamibot.app/e/sample.webp',
            'width': 512, 'height': 512}})
        result = message_media(self.message(embeds=[embed]), f'[□]({original})', True)
        self.assertEqual(len(result['media']), 1)
        self.assertEqual(result['media'][0]['url'], original)
        self.assertEqual(result['media'][0]['width'], 512)

    def test_layout_uses_actual_decoded_size_for_small_sticker(self):
        item = dict(url='https://cdn.discordapp.com/stickers/1.png', label='스티커', kind='sticker', width=160, height=160)
        entries, width, height = preview_layout([item], 320, lambda key: (100, 84))
        self.assertEqual((width, height), (100, 84))
        self.assertEqual(entries[0]['key'][1], (160, 160))

    def test_sticker_transparent_padding_is_removed_without_upscaling(self):
        raw = BytesIO(); picture = Image.new('RGBA', (320, 320))
        picture.paste((0, 0, 255, 255), (100, 100, 200, 180)); picture.save(raw, 'PNG')
        cache = ImageCache(Queue())
        try:
            with patch('desktop_images.urlopen', return_value=BytesIO(raw.getvalue())):
                cache.download(('https://cdn.discordapp.com/stickers/1.png', (160, 220), 'sticker'))
            self.assertEqual(cache.events.get_nowait()[2].size, (100, 80))
        finally:
            cache.close()

    def message(self, **kwargs):
        return Row(attachments=kwargs.get('attachments', []), stickers=kwargs.get('stickers', []),
                   embeds=kwargs.get('embeds', []))

    def test_default_hides_embed_and_media_but_preserves_text(self):
        embed = discord.Embed(title='제목', description='설명')
        embed.set_image(url='https://cdn.discordapp.com/test.png')
        row = self.message(embeds=[embed])
        result = message_media(row, '본문 <:smile:123> [□](https://cdn.kamibot.app/e/test.webp?ex=123)')
        self.assertEqual(result['media'], [])
        self.assertIn('본문', result['text'])
        self.assertIn(':smile:', result['text'])
        self.assertIn('[미디어 숨김]', result['text'])
        self.assertNotIn('https://', result['text'])
        self.assertNotIn('제목', result['text'])

    def test_enabled_extracts_attachments_stickers_emoji_and_embed(self):
        embed = discord.Embed(title='제목', description='설명')
        embed.add_field(name='항목', value='값')
        embed.set_image(url='https://cdn.discordapp.com/embed.png')
        row = self.message(embeds=[embed],
            attachments=[Row(url='https://cdn.discordapp.com/attach.png', proxy_url='', filename='사진', content_type='image/png', width=1000, height=600)],
            stickers=[Row(url='https://cdn.discordapp.com/stickers/123.png', name='스티커')])
        result = message_media(row, '본문 <a:dance:123>', True)
        self.assertEqual(len(result['media']), 4)
        self.assertEqual({item['kind'] for item in result['media']}, {'emoji', 'image', 'sticker'})
        self.assertIn('제목\n설명\n항목\n값', result['text'])

    def test_proxy_and_signed_urls_preserved_and_duplicates_removed(self):
        url = 'https://cdn.kamibot.app/e/sample.webp?ex=123&hm=abc'
        result = message_media(self.message(), f'[□]({url}) {url}', True)
        self.assertEqual(len(result['media']), 1)
        self.assertEqual(result['media'][0]['url'], url)
        self.assertTrue(image_host('https://images-ext-1.discordapp.net/external/abc/a.png'))
        self.assertFalse(image_host('http://cdn.discordapp.com/a.png'))

    def test_large_preview_keeps_aspect_ratio(self):
        raw = BytesIO(); Image.new('RGB', (1200, 600), 'blue').save(raw, 'PNG')
        cache = ImageCache(Queue())
        try:
            with patch('desktop_images.urlopen', return_value=BytesIO(raw.getvalue())):
                cache.download(('https://cdn.kamibot.app/e/sample.png', (320, 220), None))
            self.assertEqual(cache.events.get_nowait()[2].size, (320, 160))
        finally:
            cache.close()
