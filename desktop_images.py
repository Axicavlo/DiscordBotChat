"""Background Discord image loading; Tk objects stay on the UI thread."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from io import BytesIO
import time
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageOps, ImageTk
from chatbot_core.media import image_host
from dataclasses import dataclass


@dataclass
class Animation:
    frames: list
    durations: list
    loop: int | None = 0


def decode_media(data, size, trim=False):
    with Image.open(BytesIO(data)) as source:
        if source.width * source.height > 20_000_000:
            raise ValueError("Image dimensions too large")
        frames, durations = [], []
        loop = source.info.get("loop")
        count = min(getattr(source, "n_frames", 1), 120)
        for index in range(count):
            source.seek(index)
            frame = source.convert("RGBA")
            if count == 1 and trim:
                bounds = frame.getchannel("A").getbbox()
                if bounds:
                    frame = frame.crop(bounds)
            frame.thumbnail(size, Image.Resampling.LANCZOS)
            if (len(frames)+1) * frame.width * frame.height > 8_000_000:
                break
            frames.append(frame)
            durations.append(max(20, int(source.info.get("duration", 100) or 100)))
        if len(frames) == 1:
            return frames[0]
        if trim:
            boxes = [frame.getchannel("A").getbbox() for frame in frames]
            boxes = [box for box in boxes if box]
            if boxes:
                bounds = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                          max(b[2] for b in boxes), max(b[3] for b in boxes))
                frames = [frame.crop(bounds) for frame in frames]
        return Animation(frames, durations, loop)


class ImageCache:
    def __init__(self, events):
        self.events = events
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='images')
        self.photos = OrderedDict()
        self.animations = OrderedDict()
        self.alternatives = {}
        self.errors = {}
        self.pending = set()
        self.failed = {}

    def get(self, url, size, circle=True, candidates=None):
        key = (url, size, circle)
        if candidates:
            self.alternatives[key] = tuple(candidate for candidate in candidates if image_host(candidate))
        if key in self.photos:
            self.photos.move_to_end(key)
            return self.photos[key]
        if not url or key in self.pending or self.failed.get(key, 0) > time.monotonic():
            return None
        if not image_host(url):
            return None
        self.pending.add(key)
        self.pool.submit(self.download, key)
        return None

    def download(self, key):
        url, size, circle = key
        media = circle in (None, 'emoji', 'sticker')
        result = None
        candidates = list(dict.fromkeys((url, *self.alternatives.get(key, ()))))
        for candidate in candidates:
            try:
                request = Request(candidate, headers={'User-Agent': 'DiscordBotChat/1.3.1',
                                                     'Accept': 'image/*', 'Referer': 'https://discord.com/'})
                limit = 8 * 1024 * 1024 if media else 1024 * 1024
                with urlopen(request, timeout=8) as response:
                    data = response.read(limit + 1)
                if len(data) > limit:
                    raise ValueError('Image too large')
                if media:
                    result = decode_media(data, size, trim=circle in ('emoji', 'sticker'))
                else:
                    with Image.open(BytesIO(data)) as source:
                        if source.width * source.height > 512 * 512:
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
                self.errors.pop(key, None)
                break
            except Exception as error:
                self.errors[key] = type(error).__name__ + ':' + str(getattr(error, 'code', ''))
                if hasattr(error, 'close'):
                    error.close()
        self.events.put(('image_loaded', key, result))

    def current(self, key, now=None):
        animation = self.animations.get(key)
        if animation is None:
            return self.photos.get(key)
        frames, durations, loop, started = animation
        elapsed = max(0, ((now if now is not None else time.monotonic()) - started) * 1000)
        total = sum(durations)
        if loop != 0 and elapsed >= total * ((loop or 0) + 1):
            return frames[-1]
        position = elapsed % total
        for frame, duration in zip(frames, durations):
            if position < duration:
                return frame
            position -= duration
        return frames[-1]

    def finish(self, key, result):
        self.pending.discard(key)
        if result is None:
            self.failed[key] = time.monotonic() + 30
            if len(self.failed) > 512:
                self.failed.pop(next(iter(self.failed)))
            return
        if isinstance(result, Animation):
            frames = [ImageTk.PhotoImage(frame) for frame in result.frames]
            self.animations[key] = (frames, result.durations, result.loop, time.monotonic())
            self.photos[key] = frames[0]
        else:
            self.photos[key] = ImageTk.PhotoImage(result)
        while len(self.photos) > 512:
            evicted, _ = self.photos.popitem(last=False)
            self.animations.pop(evicted, None)
            self.alternatives.pop(evicted, None)
        media_keys = [item for item in self.photos if item[2] in (None, 'emoji', 'sticker')]
        for item in media_keys[:-64]:
            self.photos.pop(item, None)
            self.animations.pop(item, None)
            self.alternatives.pop(item, None)
        while sum(sum(frame.width()*frame.height() for frame in value[0])
                  for value in self.animations.values()) > 8_000_000:
            evicted, _ = self.animations.popitem(last=False)
            self.photos.pop(evicted, None)

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
