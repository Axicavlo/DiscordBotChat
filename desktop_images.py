"""Background Discord image loading; Tk objects stay on the UI thread."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from io import BytesIO
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageOps, ImageTk


class ImageCache:
    def __init__(self, events):
        self.events = events
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='images')
        self.photos = OrderedDict()
        self.pending = set()
        self.failed = {}

    def get(self, url, size, circle=True):
        key = (url, size, circle)
        if key in self.photos:
            self.photos.move_to_end(key)
            return self.photos[key]
        if not url or key in self.pending or self.failed.get(key, 0) > time.monotonic():
            return None
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in ('cdn.discordapp.com', 'media.discordapp.net'):
            return None
        self.pending.add(key)
        self.pool.submit(self.download, key)
        return None

    def download(self, key):
        url, size, circle = key
        try:
            request = Request(url, headers={'User-Agent': 'DiscordBotChat/1.3.1'})
            with urlopen(request, timeout=8) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('Image too large')
            with Image.open(BytesIO(data)) as source:
                if source.width > 512 or source.height > 512:
                    raise ValueError('Image dimensions too large')
                result = ImageOps.fit(source.convert('RGBA'), (size * 3, size * 3))
            mask = Image.new('L', result.size)
            draw = ImageDraw.Draw(mask)
            if circle:
                draw.ellipse((0, 0, result.width-1, result.height-1), fill=255)
            else:
                draw.rounded_rectangle((0, 0, result.width-1, result.height-1), radius=24, fill=255)
            result.putalpha(mask)
            result = result.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            result = None
        self.events.put(('image_loaded', key, result))

    def finish(self, key, result):
        self.pending.discard(key)
        if result is None:
            self.failed[key] = time.monotonic() + 30
            if len(self.failed) > 512:
                self.failed.pop(next(iter(self.failed)))
            return
        self.photos[key] = ImageTk.PhotoImage(result)
        while len(self.photos) > 512:
            self.photos.popitem(last=False)

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
