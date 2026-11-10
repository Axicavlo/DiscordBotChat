"""Single-message Discord controls for the shared dice tournament engine."""
import asyncio
import copy
import json
import os
import re
import traceback
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import discord
from discord import app_commands

from .tournament import START_HP, Tournament
from .tournament_media import battle_media, bracket_media, match_media, ROLL_FRAME_MS, TURN_SECONDS


def safe_name(value):
    return discord.utils.escape_markdown(value.replace('\n', ' ').replace('\r', ' '))


def battle_pages(logs):
    """Format saved logs without changing tournament state or old saves."""
    battles, current = [], None
    for entry in logs:
        match = re.fullmatch(r'(?:본선 \d+라운드|준결승|패자부활전|3·4위전|결승전) · (.+) vs (.+)', entry)
        roll = re.fullmatch(r'(.+) ([1-6]):([1-6]) (.+) · HP \d+:\d+', entry)
        if match:
            current = [f'{match[1]} VS {match[2]}']
            battles.append(current)
        elif current is not None and roll:
            a, x, y, b = roll.groups()
            x, y = int(x), int(y)
            damage = f'{a if x < y else b} HP-{abs(x-y)}' if x != y else '피해 없음'
            current.append(f'    {x}  :  {y}  => {damage}')
        elif current is not None and entry.endswith(' 승리'):
            current.append(entry)
            current = None
    pages = []
    for battle in battles:
        # Repeat the matchup on overflow pages; never mix two matches.
        page = [battle[0]]
        for line in battle[1:]:
            if len('\n'.join(safe_name(x) for x in page + [line])) > 3500:
                pages.append(page)
                page = [battle[0]]
            page.append(line)
        pages.append(page)
    return pages or [['아직 경기 기록이 없습니다.']]


class TournamentService:
    def __init__(self, client, state_dir=None):
        self.client = client
        root = Path(state_dir) if state_dir else Path(os.getenv('LOCALAPPDATA') or Path.home()) / 'DiscordBotChat'
        self.root = root
        self.rooms = {}
        self.tasks = {}
        self.lock = asyncio.Lock()
        self.file = None
        self.process_lock = None
        self.enabled = False
        self.tree = app_commands.CommandTree(client)
        self.tree.on_error = self.command_error
        self.tree.add_command(app_commands.Command(name='펩시봇', description='펩시봇 명령어 목록을 봅니다.', callback=self.help))
        tournament = app_commands.Group(name='주작기', description='주작기 토너먼트')
        tournament.add_command(app_commands.Command(name='시작', description='주작기 토너먼트 방 생성', callback=self.create))
        tournament.add_command(app_commands.Command(name='종료', description='주작기 토너먼트 종료', callback=self.stop))
        tournament.add_command(app_commands.Command(name='참가', description='주작기 토너먼트 참가', callback=self.join))
        self.tree.add_command(tournament)

    def notify(self, text):
        self.client.events.put(('error', None, text))

    def error_detail(self, context, error):
        error = getattr(error, 'original', error)
        frames = traceback.extract_tb(error.__traceback__)
        location = f'{Path(frames[-1].filename).name}:{frames[-1].lineno}' if frames else context
        detail = f'{type(error).__name__} / {location}'
        if isinstance(error, discord.HTTPException):
            detail += f' / HTTP {error.status} / {error.code}'
        # Record locations and types only: never log tokens, URLs or exception text.
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / 'tournament-errors.log').open('a', encoding='utf-8') as log:
                log.write(f'{datetime.now(timezone.utc).isoformat()} {context}: {detail}\n')
        except OSError:
            pass
        self.notify(f'주작기 {context} 실패: {detail}')
        return detail

    @staticmethod
    def is_component(interaction):
        return getattr(interaction, 'type', discord.InteractionType.component) == discord.InteractionType.component

    async def finish_success(self, interaction):
        if not self.is_component(interaction):
            await interaction.delete_original_response()

    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title='펩시봇 명령어', colour=0x00A6BD)
        entries = []
        for command in self.tree.walk_commands():
            if isinstance(command, app_commands.Command):
                name = command.qualified_name
                if name == '숫자야구':
                    name += ' 중복가능:y/n'
                entries.append(f'**/{name}**\n{command.description}')
        embed.description = '\n\n'.join(entries)
        await interaction.response.send_message(embed=embed, ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    async def command_error(self, interaction, error):
        detail = self.error_detail('명령 처리', error)
        text = f'처리하지 못했습니다. 봇 앱의 오류 기록을 확인하세요.\n오류: {detail}'
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    async def setup(self):
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.file = self.root / f'tournament-{self.client.user.id}.json'
            self.process_lock = open(self.file.with_suffix('.lock'), 'a+b')
            self.process_lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                self.process_lock.write(b'0')
                self.process_lock.flush()
                self.process_lock.seek(0)
                msvcrt.locking(self.process_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.file.exists():
                data = json.loads(self.file.read_text(encoding='utf-8'))
                self.rooms = {k: Tournament.restore(v) for k, v in data.items()}
            self.enabled = True
            for key, room in self.rooms.items():
                self.client.add_view(RoomView(self, key), message_id=room.data['message'])
        except (OSError, ValueError, KeyError, TypeError):
            self.notify('추첨 기능을 시작하지 못했습니다. 다른 앱의 동일 봇 실행 또는 추첨 저장 파일을 확인하세요.')
            self.release()
            return
        try:
            await self.tree.sync()
        except discord.HTTPException:
            self.notify('추첨 명령어 등록 실패: 봇의 applications.commands 권한과 연결을 확인하세요.')

    def save(self):
        temp = self.file.with_suffix('.tmp')
        temp.write_text(json.dumps({k: r.data for k, r in self.rooms.items()}, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.file)

    def release(self):
        self.enabled = False
        if self.process_lock:
            self.process_lock.close()
            self.process_lock = None

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.release()

    async def ready(self):
        if not self.enabled:
            return
        for key, room in self.rooms.items():
            if room.data['status'] == '진행 중':
                self.launch(key)
            elif room.data.get('dirty'):
                try:
                    await self.edit(key)
                except (OSError, discord.HTTPException):
                    self.notify('저장된 추첨 결과의 메시지 갱신에 실패했습니다.')

    def launch(self, key):
        if key not in self.tasks or self.tasks[key].done():
            self.tasks[key] = asyncio.create_task(self.run(key))

    def room_in(self, channel):
        return next((key for key, r in self.rooms.items()
                     if r.data['channel'] == channel and r.data['status'] in ('모집 중', '진행 중')), None)

    async def create(self, interaction: discord.Interaction, 제목: str = '주작기 토너먼트'):
        if not self.enabled or not interaction.guild:
            await interaction.response.send_message('서버에서 추첨 기능이 활성화된 앱으로 사용하세요.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.lock:
            if self.room_in(interaction.channel_id):
                await interaction.followup.send('이 채널에는 모집 또는 진행 중인 주작기가 있습니다. 종료 후 새 주작기를 생성하세요.', ephemeral=True)
                return
            room = Tournament(interaction.user.id, 제목.strip()[:100] or '주작기 토너먼트', interaction.channel_id, interaction.guild_id)
            key = str(interaction.id)
            self.rooms[key] = room
            message = None
            try:
                message = await interaction.channel.send(embed=self.embed(room), view=RoomView(self, key), allowed_mentions=discord.AllowedMentions.none())
                room.data['message'] = message.id
                self.save()
            except Exception:
                self.rooms.pop(key, None)
                if message:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        self.notify('추첨방 저장에 실패했습니다. 생성된 메시지를 직접 삭제하세요.')
                raise
        await interaction.delete_original_response()

    async def join(self, interaction: discord.Interaction):
        key = self.room_in(interaction.channel_id)
        if not key:
            await interaction.response.send_message('이 채널에는 참가할 추첨이 없습니다.', ephemeral=True)
            return
        await self.action(interaction, key, 'join')

    async def stop(self, interaction: discord.Interaction):
        key = self.room_in(interaction.channel_id)
        if not key:
            await interaction.response.send_message('이 채널에는 진행 중인 추첨이 없습니다.', ephemeral=True)
            return
        await self.action(interaction, key, 'stop')

    async def edit(self, key, rolling=False, animate=False, media=None):
        room = self.rooms[key]
        channel = self.client.get_channel(room.data['channel'])
        if channel is None:
            channel = await asyncio.wait_for(self.client.fetch_channel(room.data['channel']), timeout=20)
        message = channel.get_partial_message(room.data['message'])
        embed = self.embed(room)
        attachments = []
        if room.data['status'] == '진행 중' and room.data['current'] and not room.data.get('error'):
            if media is None:
                filename, data = await asyncio.wait_for(asyncio.to_thread(battle_media, room, rolling, animate), timeout=10)
            else:
                filename, data = media
            embed.set_image(url=f'attachment://{filename}')
            attachments.append(discord.File(BytesIO(data), filename=filename))
        try:
            await asyncio.wait_for(message.edit(embed=embed, view=RoomView(self, key), attachments=attachments,
                                                allowed_mentions=discord.AllowedMentions.none()), timeout=20)
        finally:
            for attachment in attachments:
                attachment.close()
        if room.data.get('dirty'):
            room.data['dirty'] = False
            self.save()

    def embed(self, room):
        d = room.data
        embed = discord.Embed(title=f"🎲 {d['title']}", colour=0x00A6BD)
        embed.set_footer(text=f"방장 ID {d['owner']} · {d['status']}")
        if d['status'] == '모집 중':
            # Native mention tags show guild nicknames without expanding long
            # names into the embed's character budget. Keep all 128 visible.
            listing = ' · '.join(f'<@{uid}>' for uid in d['players']) or '아직 참가자가 없습니다.'
            embed.description = f"참가자 **{len(d['players'])}명**\n{listing}\n\n❤️ HP {START_HP}\n🏆 3·4위전 → 결승전"
        elif d['status'] == '종료':
            lines, rank = [], 1
            for group in room.standings():
                label = {1: '🥇 1위', 2: '🥈 2위', 3: '🥉 3위'}.get(rank, f'{rank}위')
                if len(group) > 1:
                    label = f'공동 {rank}위'
                lines.append(f"**{label}** · " + ' · '.join(safe_name(room.name(p)) for p in group))
                rank += len(group)
            result = '\n'.join(lines)
            embed.description = ('🏆 **최종 결과**\n\n' + result)[:3800]
            if len(result) > 3700:
                embed.add_field(name='전체 순위', value='[전체 순위] 버튼에서 확인하세요.', inline=False)
        elif d['status'] == '취소':
            embed.description = '방장이 주작기를 종료했습니다.'
        else:
            m = d['current']
            embed.description = f"**{d['stage']}**"
            if d.get('error'):
                embed.description += '\n⚠️ 진행을 중단했습니다. 봇 앱을 다시 연결하면 이어집니다.'
                embed.add_field(name='오류', value=d['error'], inline=False)
            if m:
                embed.description += f"\n{safe_name(room.name(m['a']))} VS {safe_name(room.name(m['b']))}"
        return embed

    async def action(self, interaction, key, action, users=None):
        if not self.enabled or key not in self.rooms:
            await interaction.response.send_message('추첨을 사용할 수 없습니다.', ephemeral=True)
            return
        room = self.rooms[key]
        d = room.data
        if action in ('manage', 'start', 'stop', 'add', 'remove') and interaction.user.id != d['owner']:
            await interaction.response.send_message('방장만 사용할 수 있습니다.', ephemeral=True)
            return
        if action == 'manage':
            if d['status'] != '모집 중':
                await interaction.response.send_message('모집 중에만 참가자를 변경할 수 있습니다.', ephemeral=True)
                return
            await interaction.response.send_message('추가하거나 제외할 서버 멤버를 선택하세요.', view=ManageView(self, key), ephemeral=True)
            return
        if action in ('bracket', 'history', 'ranks'):
            await self.details(interaction, room, action)
            return
        if self.is_component(interaction):
            await interaction.response.defer(thinking=False)
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with self.lock:
                previous = copy.deepcopy(d)
                if action == 'join':
                    if interaction.user.bot:
                        raise ValueError('봇 계정은 참가할 수 없습니다.')
                    room.add(interaction.user.id, interaction.user.display_name)
                elif action == 'leave':
                    room.remove(interaction.user.id)
                elif action in ('add', 'remove'):
                    if d['status'] != '모집 중':
                        raise ValueError('모집이 마감되었습니다.')
                    eligible = [u for u in users if not u.bot] if action == 'add' else users
                    additions = [u for u in eligible if str(u.id) not in d['players']]
                    if action == 'add' and len(d['players']) + len(additions) > 128:
                        raise ValueError('참가자는 최대 128명입니다.')
                    for user in eligible:
                        if action == 'add' and str(user.id) not in d['players']:
                            room.add(user.id, user.display_name)
                        elif action == 'remove' and str(user.id) in d['players']:
                            room.remove(user.id)
                elif action == 'start':
                    guild = self.client.get_guild(d['guild'])
                    channel = self.client.get_channel(d['channel'])
                    if guild and guild.me and channel:
                        permissions = channel.permissions_for(guild.me)
                        required = [('view_channel', '채널 보기'), ('send_messages', '메시지 보내기'),
                                    ('embed_links', '링크 첨부'), ('attach_files', '파일 첨부')]
                        missing = [label for name, label in required if not getattr(permissions, name)]
                        if missing:
                            raise ValueError('이 채널에서 봇 권한이 부족합니다: ' + ', '.join(missing))
                    room.start()
                elif action == 'stop':
                    if d['status'] not in ('모집 중', '진행 중'):
                        raise ValueError('이미 종료된 추첨입니다.')
                    d['status'] = '취소'
                d['dirty'] = True
                try:
                    self.save()
                except OSError:
                    room.data = previous
                    raise
                if action == 'start':
                    self.launch(key)
                else:
                    try:
                        await self.edit(key)
                    except discord.NotFound:
                        if action != 'stop':
                            raise
            await self.finish_success(interaction)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception as error:
            detail = self.error_detail('버튼 처리', error)
            await interaction.followup.send(f'처리하지 못했습니다. 봇 앱의 오류 기록을 확인하세요.\n오류: {detail}', ephemeral=True)

    async def details(self, interaction, room, action):
        d = room.data
        if action == 'history':
            pages = battle_pages(d['logs'])
            view = PageView([], pages=pages)
            await interaction.response.send_message(embed=view.page(view.pages, 0), view=view, ephemeral=True)
            return
        elif action == 'ranks':
            lines, rank = [], 1
            for group in room.standings():
                lines.extend(f"{'공동 ' if len(group) > 1 else ''}{rank}위 · {room.name(p)}" for p in group)
                rank += len(group)
            lines = lines or ['아직 최종 순위가 없습니다.']
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
            filename, data = await asyncio.to_thread(bracket_media, copy.deepcopy(d))
            embed = discord.Embed(title='주작 대진표', colour=0x00A6BD)
            embed.set_image(url=f'attachment://{filename}')
            attachment = discord.File(BytesIO(data), filename=filename)
            try:
                await interaction.followup.send(embed=embed, file=attachment, ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())
            finally:
                attachment.close()
            return
        view = PageView(lines)
        await interaction.response.send_message(embed=view.page(view.pages, 0), view=view, ephemeral=True)

    async def wait_animation(self, deadline):
        await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()))

    async def run(self, key):
        room = self.rooms[key]
        try:
            while room.data['status'] == '진행 중':
                await self.client.wait_until_ready()
                async with self.lock:
                    if room.data['status'] != '진행 중':
                        break
                    if room.data.pop('error', None):
                        self.save()
                    m = room.data['current']
                    if m and min(m['hp']) == 0:
                        previous = copy.deepcopy(room.data)
                        room.next_match()
                        room.data['dirty'] = True
                        try:
                            self.save()
                        except OSError:
                            room.data = previous
                            raise
                    if room.data['status'] == '종료':
                        await self.edit(key)
                        break
                    m = room.data['current']
                    plan = m.get('animation_plan')
                    if not plan or plan['cursor'] >= len(plan['rolls']):
                        m['animation_plan'] = room.plan_match()
                        self.save()
                    snapshot = copy.deepcopy(room.data)
                # Rendering outside the state lock leaves the stop button usable.
                media = await asyncio.wait_for(asyncio.to_thread(match_media, snapshot), timeout=60)
                async with self.lock:
                    if room.data['status'] != '진행 중':
                        break
                    await self.edit(key, media=media)
                started = asyncio.get_running_loop().time()
                plan = snapshot['current']['animation_plan']
                for offset, dice in enumerate(plan['rolls'][plan['cursor']:]):
                    base = started + offset * TURN_SECONDS
                    step = ROLL_FRAME_MS / 1000
                    await self.wait_animation(base + 3 * step)
                    async with self.lock:
                        if room.data['status'] != '진행 중':
                            return
                        previous = copy.deepcopy(room.data)
                        room.roll(dice)
                        room.data['current']['animation_plan']['cursor'] += 1
                        room.data['dirty'] = True
                        try:
                            self.save()
                        except OSError:
                            room.data = previous
                            raise
                    await self.wait_animation(base + TURN_SECONDS)
                    if min(room.data['current']['hp']) == 0:
                        break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            detail = self.error_detail('경기 진행', error)
            if room.data['status'] == '진행 중':
                room.data['error'] = detail
                try:
                    self.save()
                    await self.edit(key)
                except Exception:
                    pass


class RoomView(discord.ui.View):
    def __init__(self, service, key):
        super().__init__(timeout=None)
        self.service, self.key = service, key
        status = service.rooms[key].data['status']
        for label, action, row in [('참가', 'join', 0), ('참가 취소', 'leave', 0),
                                   ('참가자 관리', 'manage', 0), ('시작', 'start', 1), ('종료', 'stop', 1),
                                   ('대진표', 'bracket', 2), ('경기 기록', 'history', 2), ('전체 순위', 'ranks', 2)]:
            button = discord.ui.Button(label=label, custom_id=f'tournament:{key}:{action}', row=row,
                                       style=discord.ButtonStyle.primary if action in ('join', 'start') else discord.ButtonStyle.secondary)
            if action in ('join', 'leave', 'manage', 'start'):
                button.disabled = status != '모집 중'
            elif action == 'stop':
                button.disabled = status not in ('모집 중', '진행 중')
            async def callback(interaction, action=action):
                await service.action(interaction, key, action)
            button.callback = callback
            self.add_item(button)

    async def on_error(self, interaction, error, item):
        detail = self.service.error_detail('버튼 응답', error)
        text = f'처리하지 못했습니다. 봇 앱의 오류 기록을 확인하세요.\n오류: {detail}'
        if not interaction.response.is_done():
            await interaction.response.send_message(text, ephemeral=True)
        else:
            await interaction.followup.send(text, ephemeral=True)


class ManageView(discord.ui.View):
    def __init__(self, service, key):
        super().__init__(timeout=180)
        self.service = service
        for action, label in [('add', '참가자로 추가할 멤버 선택'), ('remove', '참가에서 제외할 멤버 선택')]:
            select = discord.ui.UserSelect(placeholder=label, min_values=1, max_values=25)
            async def callback(interaction, action=action, select=select):
                await service.action(interaction, key, action, select.values)
            select.callback = callback
            self.add_item(select)

    async def on_error(self, interaction, error, item):
        await RoomView.on_error(self, interaction, error, item)


class PageView(discord.ui.View):
    def __init__(self, lines, pages=None):
        super().__init__(timeout=180)
        self.pages = pages if pages is not None else [lines[i:i + 10] for i in range(0, len(lines), 10)]
        self.pages = self.pages or [['표시할 내용이 없습니다.']]
        self.index = 0
        for label, step in [('이전', -1), ('다음', 1)]:
            button = discord.ui.Button(label=label)
            async def callback(interaction, step=step):
                self.index = max(0, min(len(self.pages) - 1, self.index + step))
                await interaction.response.edit_message(embed=self.page(self.pages, self.index), view=self)
            button.callback = callback
            self.add_item(button)

    @staticmethod
    def page(pages, index):
        return discord.Embed(title=f'주작 상세 · {index + 1}/{len(pages)}',
                             description='\n'.join(safe_name(x) for x in pages[index])[:4000], colour=0x00A6BD)
