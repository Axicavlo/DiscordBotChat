"""Shared Discord behavior for Windows and Android. No UI or OS imports."""
import asyncio
import time
import discord

from .version import VERSION
from .tournament_discord import TournamentService
from .number_baseball import NumberBaseballService


def server_display_name(user, guild=None, names=None):
    if guild is not None and names is not None:
        cached = names.get((guild.id, user.id))
        if cached:
            return cached
    if guild is None or getattr(getattr(user, 'guild', None), 'id', None) == guild.id:
        member = user
    else:
        member = guild.get_member(user.id)
    return (getattr(member, 'nick', None) or getattr(member, 'global_name', None)
            or getattr(member, 'display_name', None) or getattr(user, 'global_name', None)
            or getattr(user, 'display_name', None) or getattr(user, 'name', None) or '알 수 없는 사용자')


def message_text(message, names=None, include_extras=True):
    body = message.clean_content
    if message.reference:
        original = message.reference.resolved
        if isinstance(original, discord.Message):
            preview = original.clean_content.replace('\n', ' ')[:80] or '[첨부 메시지]'
            body = f'↳ {server_display_name(original.author, original.guild, names)}: {preview}\n{body}'
        else:
            body = f'↳ 원본 메시지 (ID: {message.reference.message_id})\n{body}'
    extras = [a.url for a in message.attachments] if include_extras else []
    if include_extras:
        extras += [e.title or e.description or '[임베드]' for e in message.embeds]
    if extras:
        body += '\n' + '\n'.join(extras)
    name = server_display_name(message.author, getattr(message, 'guild', None), names)
    return f'{message.created_at.astimezone():%m/%d %H:%M}  {name}\n{body or "[내용 없음]"}\n'


def message_view(message, names=None, visible=False):
    from .media import message_media
    body = message_text(message, names, include_extras=False).split('\n', 1)[1].rstrip('\n')
    if not message.clean_content and not message.reference:
        body = ''
    return message_media(message, body, visible)


def asset_url(asset):
    return str(asset.with_format('png').with_size(64)) if asset else ''


def avatar_url(user, guild=None, avatars=None):
    key = (getattr(guild, 'id', None), user.id)
    if avatars and key in avatars:
        return avatars[key]
    return asset_url(getattr(user, 'display_avatar', None))


class Bridge(discord.Client):
    def __init__(self, events, state_dir=None):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.events = events
        self.worker_loop = None
        self.member_names = {}
        self.member_avatars = {}
        self._name_expiry = {}
        self._name_tasks = {}
        self._name_slots = asyncio.Semaphore(4)
        self.tournaments = TournamentService(self, state_dir)
        self.number_baseball = NumberBaseballService(self.tournaments.tree)

    async def setup_hook(self):
        await self.tournaments.setup()

    async def close(self):
        await self.number_baseball.close()
        await self.tournaments.close()
        await super().close()

    async def _fetch_member_name(self, guild, user):
        key = (guild.id, user.id)
        async with self._name_slots:
            try:
                member = await guild.fetch_member(user.id)
                self.member_names[key] = server_display_name(member, guild)
                self.member_avatars[key] = avatar_url(member)
                self._name_expiry[key] = time.monotonic() + 300
            except discord.HTTPException:
                # A departed member or denied lookup must not break messages.
                self._name_expiry[key] = time.monotonic() + 30

    async def prepare_member_names(self, messages):
        participants = {}
        for message in messages:
            referenced = getattr(getattr(message, 'reference', None), 'resolved', None)
            sources = [message] + ([referenced] if isinstance(referenced, discord.Message) else [])
            for source in sources:
                guild = getattr(source, 'guild', None)
                if guild is None:
                    continue
                for user in [source.author, *source.mentions]:
                    key = (guild.id, user.id)
                    if getattr(getattr(user, 'guild', None), 'id', None) == guild.id:
                        self.member_names[key] = server_display_name(user, guild)
                        self.member_avatars[key] = avatar_url(user)
                        self._name_expiry[key] = time.monotonic() + 300
                    else:
                        participants[key] = (guild, user)
        jobs = []
        for key, (guild, user) in participants.items():
            if self._name_expiry.get(key, 0) > time.monotonic():
                continue
            task = self._name_tasks.get(key)
            if task is None:
                task = asyncio.create_task(self._fetch_member_name(guild, user))
                self._name_tasks[key] = task
                task.add_done_callback(lambda done, key=key: self._name_tasks.pop(key, None))
            jobs.append(task)
        if jobs:
            try:
                await asyncio.wait_for(asyncio.gather(*jobs, return_exceptions=True), timeout=8)
            except asyncio.TimeoutError:
                pass

    async def on_ready(self):
        self.events.put(('ready', None, str(self.user)))
        await self.publish_servers()
        await self.tournaments.ready()

    async def on_resumed(self):
        self.events.put(('ready', None, str(self.user)))
        await self.publish_servers()
        await self.tournaments.ready()

    async def on_disconnect(self):
        self.events.put(('status', None, '연결 끊김 · 재연결 대기 중'))

    async def publish_servers(self):
        self.events.put(('server_icons', None, {g.id: asset_url(g.icon) for g in self.guilds}))
        self.events.put(('servers', None, sorted([(g.id, g.name) for g in self.guilds], key=lambda x: x[1])))

    async def on_guild_update(self, before, after):
        await self.publish_servers()

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
        await self.prepare_member_names(rows)
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

    async def own_message(self, channel_id, message_id):
        channel = self.get_channel(channel_id)
        if channel is None:
            raise RuntimeError('채널에 접근할 수 없습니다.')
        message = await channel.fetch_message(message_id)
        if self.user is None or message.author.id != self.user.id:
            raise RuntimeError('이 봇이 보낸 메시지만 편집·삭제할 수 있습니다.')
        return message

    async def edit_text(self, channel_id, message_id, text):
        if not text.strip() or len(text) > 2000:
            raise RuntimeError('메시지는 공백이 아닌 1~2,000자로 입력하세요.')
        message = await self.own_message(channel_id, message_id)
        updated = await message.edit(content=text, allowed_mentions=discord.AllowedMentions.none())
        await self.prepare_member_names([updated])
        self.events.put(('message', channel_id, updated))
        self.events.put(('edited', channel_id, message_id))

    async def delete_message(self, channel_id, message_id):
        message = await self.own_message(channel_id, message_id)
        await message.delete()
        self.events.put(('deleted', channel_id, message_id))

    async def on_message(self, message):
        if message.guild:
            await self.prepare_member_names([message])
            self.events.put(('message', message.channel.id, message))

    async def on_raw_message_edit(self, payload):
        try:
            channel = self.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                await self.prepare_member_names([msg])
                self.events.put(('message', payload.channel_id, msg))
        except discord.HTTPException:
            pass

    async def on_raw_message_delete(self, payload):
        self.number_baseball.message_deleted(payload.channel_id, (payload.message_id,))
        self.events.put(('deleted', payload.channel_id, payload.message_id))

    async def on_raw_bulk_message_delete(self, payload):
        self.number_baseball.message_deleted(payload.channel_id, payload.message_ids)
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

