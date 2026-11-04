"""Shared Discord behavior for Windows and Android. No UI or OS imports."""
import asyncio
import discord

from .version import VERSION


def message_text(message):
    body = message.clean_content
    if message.reference:
        original = message.reference.resolved
        if isinstance(original, discord.Message):
            preview = original.clean_content.replace('\n', ' ')[:80] or '[첨부 메시지]'
            body = f'↳ {original.author.display_name}: {preview}\n{body}'
        else:
            body = f'↳ 원본 메시지 (ID: {message.reference.message_id})\n{body}'
    extras = [a.url for a in message.attachments]
    extras += [e.title or e.description or '[임베드]' for e in message.embeds]
    if extras:
        body += '\n' + '\n'.join(extras)
    return f'{message.created_at.astimezone():%m/%d %H:%M}  {message.author.display_name}\n{body or "[내용 없음]"}\n'


class Bridge(discord.Client):
    def __init__(self, events):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.events = events
        self.worker_loop = None

    async def on_ready(self):
        self.events.put(('ready', None, str(self.user)))
        await self.publish_servers()

    async def on_resumed(self):
        self.events.put(('ready', None, str(self.user)))
        await self.publish_servers()

    async def on_disconnect(self):
        self.events.put(('status', None, '연결 끊김 · 재연결 대기 중'))

    async def publish_servers(self):
        self.events.put(('servers', None, sorted([(g.id, g.name) for g in self.guilds], key=lambda x: x[1])))

    async def on_guild_join(self, guild):
        await self.publish_servers()

    async def on_guild_remove(self, guild):
        await self.publish_servers()

    async def channels(self, guild_id):
        guild = self.get_guild(guild_id)
        if guild is None or guild.me is None:
            raise RuntimeError('서버 정보를 가져올 수 없습니다. 새로고침하세요.')
        rows = [(c.id, f'{c.category.name + " / " if c.category else ""}#{c.name}')
                for c in guild.text_channels if c.permissions_for(guild.me).view_channel]
        self.events.put(('channels', guild_id, rows))

    async def history(self, channel_id):
        channel = self.get_channel(channel_id)
        if channel is None:
            raise RuntimeError('채널에 접근할 수 없습니다.')
        rows = [m async for m in channel.history(limit=100)]
        self.events.put(('history', channel_id, list(reversed(rows))))

    async def send_text(self, channel_id, text, reply_id=None):
        channel = self.get_channel(channel_id)
        if channel is None:
            raise RuntimeError('채널에 접근할 수 없습니다.')
        reference = None
        if reply_id is not None:
            reference = discord.MessageReference(message_id=reply_id, channel_id=channel_id,
                                                 fail_if_not_exists=True)
        await channel.send(text, reference=reference,
                           allowed_mentions=discord.AllowedMentions(
                               users=True, roles=False, everyone=False, replied_user=reply_id is not None))
        self.events.put(('sent', channel_id, (text, reply_id)))

    async def on_message(self, message):
        if message.guild:
            self.events.put(('message', message.channel.id, message))

    async def on_raw_message_edit(self, payload):
        try:
            channel = self.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                self.events.put(('message', payload.channel_id, msg))
        except discord.HTTPException:
            pass

    async def on_raw_message_delete(self, payload):
        self.events.put(('deleted', payload.channel_id, payload.message_id))

    async def on_raw_bulk_message_delete(self, payload):
        for mid in payload.message_ids:
            self.events.put(('deleted', payload.channel_id, mid))

    def run_worker(self, token):
        async def main():
            self.worker_loop = asyncio.get_running_loop()
            try:
                async with self:
                    await self.start(token)
            except Exception as exc:
                self.events.put(('fatal', None, safe_error(exc)))
        asyncio.run(main())

    def submit(self, method, *args, channel_id=None):
        if not self.worker_loop or not self.is_ready():
            self.events.put(('error', channel_id, '봇 연결이 준비되지 않았습니다.'))
            return
        async def task():
            try:
                await method(*args)
            except Exception as exc:
                self.events.put(('error', channel_id, safe_error(exc)))
        asyncio.run_coroutine_threadsafe(task(), self.worker_loop)


def safe_error(exc):
    if isinstance(exc, discord.LoginFailure):
        return '봇 토큰이 올바르지 않습니다.'
    if isinstance(exc, discord.PrivilegedIntentsRequired):
        return 'Developer Portal에서 Message Content Intent를 켜주세요.'
    if isinstance(exc, discord.Forbidden):
        return '권한이 없습니다. 채널 보기·메시지 기록 보기·메시지 보내기를 확인하세요.'
    if isinstance(exc, discord.HTTPException):
        return f'Discord 요청 실패 (HTTP {exc.status}). 잠시 후 다시 시도하세요.'
    if isinstance(exc, RuntimeError):
        return str(exc)
    return f'연결 또는 처리 실패 ({type(exc).__name__}). 네트워크를 확인하세요.'

