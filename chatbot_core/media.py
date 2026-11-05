"""Extract image previews without downloading anything during message parsing."""
import re
from urllib.parse import urlsplit, unquote

EMOJI = re.compile(r'<(a?):([A-Za-z0-9_]+):(\d+)>')
LINK = re.compile(r'\[([^\]]*)\]\((https://[^\s)]+)\)')
URL = re.compile(r'https://[^\s<>\])]+')
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.apng', '.avif')


def image_host(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        return parsed.scheme == 'https' and (host in (
            'cdn.discordapp.com', 'media.discordapp.net', 'cdn.kamibot.app')
            or re.fullmatch(r'images-ext-\d+\.discordapp\.net', host) is not None)
    except ValueError:
        return False


def image_link(url):
    return image_host(url) and urlsplit(url).path.lower().endswith(IMAGE_SUFFIXES)


def image_identity(url):
    parsed = urlsplit(url)
    host, path = parsed.hostname or '', unquote(parsed.path)
    proxy = re.search(r'/external/[^/]+/(https?)/([^/]+)(/.*)', path)
    if host.startswith('images-ext-') and proxy:
        host, path = proxy.group(2), proxy.group(3)
    if host in ('cdn.discordapp.com', 'media.discordapp.net'):
        host = 'discord-cdn'
    return host, path


def preview_layout(previews, max_width, cached_size):
    """Pack repeated emoji in rows; reserve the actual decoded image bounds."""
    entries, x, y, row_height, used_width = [], 0, 0, 0, 0
    for item in previews:
        kind = item['kind']
        shape = kind if kind in ('emoji', 'sticker') else None
        limit = 32 if kind == 'emoji' else min(max_width, 160) if kind in ('sticker', 'enlarged_emoji') else max_width
        target = (limit, limit if kind in ('sticker', 'enlarged_emoji') else 32 if kind == 'emoji' else 220)
        if kind == 'enlarged_emoji':
            shape = 'sticker'
        key = (item['url'], target, shape)
        actual = cached_size(key)
        if actual:
            width, height = actual
        elif item['width'] and item['height']:
            scale = min(1, target[0] / item['width'], target[1] / item['height'])
            width, height = max(1, round(item['width'] * scale)), max(1, round(item['height'] * scale))
        else:
            width, height = limit, min(160, target[1])
        if kind != 'emoji' or x + width > max_width:
            if x:
                y += row_height + 8
                x, row_height = 0, 0
        entries.append(dict(item=item, key=key, x=x, y=y, width=width, height=height))
        used_width = max(used_width, x + width)
        if kind == 'emoji':
            x += width + 4
            row_height = max(row_height, height)
        else:
            y += height + 8
    height = y + row_height if x else max(0, y - 8)
    return entries, used_width, height


def message_media(message, body, visible=False):
    previews, seen, embed_text = [], set(), []

    def add(url, label, kind='image', width=0, height=0, repeat=False, alternatives=()):
        if kind == 'image' and ('/emojis/' in urlsplit(url).path or urlsplit(url).hostname == 'cdn.kamibot.app'):
            kind = 'enlarged_emoji'
        identity = image_identity(url) if image_host(url) else None
        if identity and (repeat or identity not in seen) and len(previews) < 20:
            seen.add(identity)
            previews.append(dict(url=url, label=label, kind=kind, width=width or 0, height=height or 0,
                                 alternatives=[candidate for candidate in alternatives if image_host(candidate) and candidate != url]))
        elif identity in seen and not repeat:
            for preview in previews:
                if image_identity(preview['url']) == identity:
                    if width and height:
                        preview.update(width=width, height=height)
                    preview['alternatives'] = list(dict.fromkeys(preview.get('alternatives', []) +
                        [candidate for candidate in alternatives if image_host(candidate) and candidate != preview['url']]))

    def emoji(match):
        animated, name, ident = match.groups()
        extension = 'gif' if animated else 'png'
        add(f'https://cdn.discordapp.com/emojis/{ident}.{extension}?size=128', name, 'emoji', 32, 32, repeat=True)
        return f':{name}:' if not visible else ''

    body = EMOJI.sub(emoji, body)
    for attachment in getattr(message, 'attachments', []):
        url = getattr(attachment, 'url', '')
        mime = getattr(attachment, 'content_type', '') or ''
        if mime.startswith('image/') or image_link(url):
            add(url if image_host(url) else getattr(attachment, 'proxy_url', ''), getattr(attachment, 'filename', '이미지'),
                width=getattr(attachment, 'width', 0), height=getattr(attachment, 'height', 0),
                alternatives=[getattr(attachment, 'proxy_url', '')])
        else:
            body += '\n' + url

    def linked(match):
        label, url = match.groups()
        if image_link(url):
            add(url, label or '이미지')
            return ''
        return match.group(0)

    body = LINK.sub(linked, body)

    def bare(match):
        url = match.group(0)
        if image_link(url):
            add(url, '이미지')
            return ''
        return url

    body = URL.sub(bare, body)
    for sticker in getattr(message, 'stickers', []):
        url = str(getattr(sticker, 'url', ''))
        if urlsplit(url).path.endswith('.json'):
            embed_text.append('[지원하지 않는 스티커: ' + sticker.name + ']')
        else:
            add(url, getattr(sticker, 'name', '스티커'), 'sticker', 160, 160)

    embeds = getattr(message, 'embeds', [])
    for embed in embeds:
        lines = [getattr(getattr(embed, 'author', None), 'name', ''),
                 getattr(embed, 'title', ''), getattr(embed, 'description', '')]
        for field in getattr(embed, 'fields', []):
            lines.extend([field.name, field.value])
        lines.append(getattr(getattr(embed, 'footer', None), 'text', ''))
        embed_text.extend(str(line) for line in lines if line)
        for part in ('image', 'thumbnail'):
            image = getattr(embed, part, None)
            original = getattr(image, 'url', '')
            url = original if image_host(original) else getattr(image, 'proxy_url', '')
            if url:
                add(url, getattr(embed, 'title', '') or '임베드 이미지',
                    width=getattr(image, 'width', 0), height=getattr(image, 'height', 0),
                    alternatives=[getattr(image, 'proxy_url', '')])
    body = body.strip()
    if visible:
        body = '\n'.join([part for part in (body, '\n'.join(embed_text)) if part])
    elif previews or embeds or embed_text:
        body = (body + '\n[미디어 숨김]').strip()
    return dict(text=body, media=previews if visible else [])
