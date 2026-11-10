"""Discord number baseball rooms and per-player guess histories."""
import asyncio
import logging
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from string import digits

import discord
from discord import app_commands

from .tournament_discord import safe_name


MAX_TURNS = 9
MAX_PLAYERS = 25
LOBBY_SECONDS = 60
GAME_SECONDS = 600
logger = logging.getLogger(__name__)


def score(answer, guess):
    remaining = [(expected, entered) for expected, entered in zip(answer, guess)
                 if expected != entered]
    expected = Counter(pair[0] for pair in remaining)
    entered = Counter(pair[1] for pair in remaining)
    return len(answer) - len(remaining), sum((expected & entered).values())


@dataclass
class Player:
    name: str
    guesses: list = field(default_factory=list)

    @property
    def result(self):
        if self.guesses and self.guesses[-1][1] == 4:
            return f'{len(self.guesses)}턴'
        if len(self.guesses) == MAX_TURNS:
            return '실패'
        return None


class GuessModal(discord.ui.Modal, title='숫자야구 · 숫자 입력'):
    guess = discord.ui.TextInput(label='네 자리 숫자', min_length=4, max_length=4)

    def __init__(self, room, turn, personal_view=None):
        super().__init__(timeout=120)
        self.room = room
        self.turn = turn
        self.personal_view = personal_view

    async def on_submit(self, interaction):
        create_result = self.personal_view is None
        await interaction.response.defer(ephemeral=create_result, thinking=create_result)
        await self.room.submit(interaction, self.turn, self.guess.value, self.personal_view)

    async def on_error(self, interaction, error):
        logger.error('Number baseball guess failed', exc_info=error)
        if interaction.response.is_done():
            await guess_error(interaction, '처리하지 못했습니다. 다시 시도해 주세요.', self.personal_view)


async def guess_error(interaction, text, personal_view):
    if personal_view is None:
        await interaction.edit_original_response(content=text)
    else:
        await interaction.followup.send(text, ephemeral=True)


class GameView(discord.ui.View):
    def __init__(self, room, started=False, personal=False):
        super().__init__(timeout=900 if personal else None)
        self.room = room
        self.personal = personal
        if started or personal:
            self.remove_item(self.join)
            self.remove_item(self.start)
        else:
            self.remove_item(self.guess)
        if personal:
            self.remove_item(self.end)

    @discord.ui.button(label='참가', style=discord.ButtonStyle.primary, custom_id='number-baseball:join')
    async def join(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.room.join(interaction)

    @discord.ui.button(label='시작', style=discord.ButtonStyle.success, custom_id='number-baseball:start')
    async def start(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.room.start(interaction)

    @discord.ui.button(label='종료', style=discord.ButtonStyle.danger)
    async def end(self, interaction, button):
        if interaction.user.id != self.room.owner:
            await interaction.response.send_message('방장만 게임을 종료할 수 있습니다.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ended = await self.room.finish()
        text = '숫자야구를 종료했습니다.' if ended else '이미 종료된 게임입니다.'
        await interaction.edit_original_response(content=text)

    @discord.ui.button(label='숫자 입력', style=discord.ButtonStyle.primary, custom_id='number-baseball:guess')
    async def guess(self, interaction, button):
        player = self.room.players.get(interaction.user.id)
        if not self.room.active or not self.room.answer or not player or player.result:
            await interaction.response.send_message('현재 숫자를 입력할 수 없습니다.', ephemeral=True)
            return
        await interaction.response.send_modal(
            GuessModal(self.room, len(player.guesses), self if self.personal else None)
        )

    async def on_error(self, interaction, error, item):
        logger.error('Number baseball button failed', exc_info=error)
        if interaction.response.is_done():
            await interaction.edit_original_response(content='처리하지 못했습니다. 다시 시도해 주세요.')
        else:
            await interaction.response.send_message('처리하지 못했습니다. 다시 시도해 주세요.', ephemeral=True)


class Room:
    def __init__(self, service, channel_id, owner, duplicates):
        self.service = service
        self.channel_id = channel_id
        self.owner = owner.id
        self.duplicates = duplicates
        self.players = {owner.id: Player(owner.display_name)}
        self.answer = None
        self.ended_early = False
        self.message = None
        self.view = GameView(self)
        self.timer = None
        self.deadline = None
        self.lock = asyncio.Lock()

    @property
    def finished(self):
        return self.ended_early or all(player.result for player in self.players.values())

    @property
    def active(self):
        return self.service.rooms.get(self.channel_id) is self

    def embed(self):
        status = '종료' if self.finished else '진행 중' if self.answer else '모집 중'
        mode = '중복 가능' if self.duplicates else '중복 금지'
        answer = self.answer if self.finished else '????'
        lines = [f'**{mode} · {status}**']
        if answer is not None:
            lines.append(f'# {answer}')
        if not self.answer and not self.finished:
            lines.append('방장이 시작하거나 방 생성 60초 뒤에 자동으로 시작합니다.')
        elif not self.finished:
            lines.append('시작 후 10분이 지나면 미완료자는 실패 처리됩니다.')
        lines.append(f'\n**참가자 ({len(self.players)}/{MAX_PLAYERS})**')
        for player in self.players.values():
            name = safe_name(player.name[:64])
            result = player.result or ('실패' if self.ended_early and self.answer else None)
            lines.append(f'{name}({result})' if result else name)
        return discord.Embed(title='숫자야구', description='\n'.join(lines), colour=0x00A6BD)

    async def join(self, interaction):
        async with self.lock:
            user = interaction.user
            if (not self.active or self.deadline is None or self.answer
                    or asyncio.get_running_loop().time() >= self.deadline):
                text = '모집이 마감되었습니다.'
            elif user.id in self.players:
                text = '이미 참가했습니다.'
            elif len(self.players) >= MAX_PLAYERS:
                text = '참가 인원이 가득 찼습니다.'
            else:
                self.players[user.id] = Player(user.display_name)
                try:
                    await self.message.edit(embed=self.embed())
                except discord.HTTPException:
                    del self.players[user.id]
                    raise
                text = '숫자야구에 참가했습니다.'
        await interaction.edit_original_response(content=text)

    async def start(self, interaction=None):
        async with self.lock:
            if not self.active or self.message is None:
                text = '현재 시작할 수 없습니다.'
            elif interaction and interaction.user.id != self.owner:
                text = '방장만 게임을 시작할 수 있습니다.'
            elif self.answer:
                text = '이미 시작한 게임입니다.'
            else:
                rng = random.SystemRandom()
                numbers = rng.choices(digits, k=4) if self.duplicates else rng.sample(digits, 4)
                self.answer = ''.join(numbers)
                view = GameView(self, started=True)
                try:
                    await self.message.edit(embed=self.embed(), view=view)
                except discord.HTTPException:
                    self.answer = None
                    view.stop()
                    raise
                self.view.stop()
                self.view = view
                if self.timer and self.timer is not asyncio.current_task():
                    self.timer.cancel()
                self.deadline = asyncio.get_running_loop().time() + GAME_SECONDS
                self.timer = asyncio.create_task(self.auto_finish())
                text = None
        if interaction:
            if text is None:
                await interaction.delete_original_response()
            else:
                await interaction.edit_original_response(content=text)

    async def auto_start(self):
        await asyncio.sleep(max(0, self.deadline - asyncio.get_running_loop().time()))
        try:
            await self.start()
        except discord.NotFound:
            self.service.remove(self)
        except discord.HTTPException:
            logger.exception('Number baseball automatic start failed')

    async def auto_finish(self):
        await asyncio.sleep(max(0, self.deadline - asyncio.get_running_loop().time()))
        await self.finish(automatic=True)

    async def finish(self, automatic=False):
        async with self.lock:
            if not self.active:
                return False
            self.ended_early = True
            try:
                await self.message.edit(embed=self.embed(), view=None)
            except discord.HTTPException:
                if not automatic:
                    self.ended_early = False
                    raise
                logger.exception('Number baseball timeout update failed')
            self.service.remove(self)
            return True

    async def submit(self, interaction, turn, guess, personal_view=None):
        async with self.lock:
            player = self.players.get(interaction.user.id)
            if not self.active or not self.answer or not player or player.result:
                text = '현재 숫자를 입력할 수 없습니다.'
            elif asyncio.get_running_loop().time() >= self.deadline:
                text = '게임 제한 시간이 지났습니다.'
            elif turn != len(player.guesses):
                text = '이미 처리된 턴입니다. 숫자 입력 버튼을 다시 눌러 주세요.'
            elif not re.fullmatch(r'[0-9]{4}', guess):
                text = '0부터 9까지의 숫자 네 자리를 입력해 주세요.'
            elif not self.duplicates and len(set(guess)) != 4:
                text = '중복되지 않는 숫자 네 자리를 입력해 주세요.'
            else:
                player.guesses.append((guess, *score(self.answer, guess)))
                if player.result:
                    try:
                        if self.finished:
                            await self.message.edit(embed=self.embed(), view=None)
                        else:
                            await self.message.edit(embed=self.embed())
                    except discord.HTTPException:
                        player.guesses.pop()
                        logger.exception('Number baseball result update failed')
                        await guess_error(interaction, '결과를 저장하지 못했습니다. 다시 입력해 주세요.', personal_view)
                        return
                    if self.finished:
                        self.service.remove(self)
                rows = ['| TURN | GUESS   | RESULT']
                for index, (entered, strikes, balls) in enumerate(player.guesses, start=1):
                    digits_row = ' '.join(entered)
                    rows.append(f'| {index:02d}   | {digits_row} | {strikes}S {balls}B')
                description = '\n'.join(f'### `{row}`' for row in rows)
                if player.result:
                    description += f'\n**{player.result}**'
                title = f'숫자야구 내 결과 ({len(player.guesses)}/{MAX_TURNS}턴)'
                embed = discord.Embed(title=title, description=description, colour=0x00A6BD)
                view = None if player.result else personal_view or GameView(self, personal=True)
                await interaction.edit_original_response(embed=embed, view=view)
                return
        await guess_error(interaction, text, personal_view)


class NumberBaseballService:
    def __init__(self, tree):
        self.rooms = {}
        tree.add_command(app_commands.Command(name='숫자야구', description='숫자야구 방생성',
                                              callback=self.create))

    @app_commands.describe(중복가능='y/n 선택 (y는 중복 허용, n은 중복 금지, 기본값 n)')
    @app_commands.choices(중복가능=[
        app_commands.Choice(name='y', value='y'),
        app_commands.Choice(name='n', value='n'),
    ])
    async def create(self, interaction: discord.Interaction, 중복가능: str = 'n'):
        if interaction.guild_id is None:
            await interaction.response.send_message('서버 채널에서 사용할 수 있습니다.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        if interaction.channel_id in self.rooms:
            await interaction.edit_original_response(content='이 채널에는 이미 숫자야구 방이 있습니다.')
            return
        room = Room(self, interaction.channel_id, interaction.user, 중복가능 == 'y')
        self.rooms[room.channel_id] = room
        try:
            room.message = await interaction.channel.send(embed=room.embed(), view=room.view)
        except (Exception, asyncio.CancelledError):
            self.remove(room)
            raise
        room.deadline = asyncio.get_running_loop().time() + LOBBY_SECONDS
        room.timer = asyncio.create_task(room.auto_start())
        await interaction.delete_original_response()

    def remove(self, room):
        if self.rooms.get(room.channel_id) is room:
            del self.rooms[room.channel_id]
        room.view.stop()
        if room.timer and room.timer is not asyncio.current_task():
            room.timer.cancel()

    def message_deleted(self, channel_id, message_ids):
        room = self.rooms.get(channel_id)
        if room and room.message and room.message.id in message_ids:
            self.remove(room)

    async def close(self):
        rooms = list(self.rooms.values())
        for room in rooms:
            self.remove(room)
        await asyncio.gather(*(room.timer for room in rooms if room.timer), return_exceptions=True)
