import asyncio
import unittest
from queue import Queue
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from chatbot_core import Bridge
from chatbot_core.number_baseball import score


def interaction(user, channel=None):
    return SimpleNamespace(user=user, guild_id=1, channel_id=10, channel=channel, followup=AsyncMock(),
                           response=AsyncMock(), edit_original_response=AsyncMock(),
                           delete_original_response=AsyncMock())


class NumberBaseballTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = Bridge(Queue())
        self.service = self.bridge.number_baseball
        self.message = AsyncMock(id=123)
        self.channel = SimpleNamespace(send=AsyncMock(return_value=self.message))
        self.owner = interaction(SimpleNamespace(id=1, display_name='펩시봇'), self.channel)
        self.guest = interaction(SimpleNamespace(id=2, display_name='참가자'), self.channel)

    async def asyncTearDown(self):
        await self.bridge.close()

    def test_scoring(self):
        guesses = ['1234', '5678', '9012', '9078', '1807']
        self.assertEqual([score('9305', guess) for guess in guesses],
                         [(0, 1), (0, 1), (1, 1), (1, 1), (1, 0)])
        self.assertEqual(score('1977', '1179'), (2, 1))
        self.assertEqual(score('0012', '2000'), (1, 2))

    async def test_help_lists_one_command_with_both_choices(self):
        await self.bridge.tournaments.help(self.owner)
        description = self.owner.response.send_message.call_args.kwargs['embed'].description
        self.assertIn('**/숫자야구 중복가능:y/n**\n숫자야구 방생성', description)
        self.assertEqual(description.count('/숫자야구'), 1)

    async def test_room_hides_answer_until_every_player_finishes(self):
        command = self.bridge.tournaments.tree.get_command('숫자야구')
        option, = command.to_dict(self.bridge.tournaments.tree)['options']
        self.assertEqual(option['name'], '중복가능')
        self.assertFalse(option['required'])
        self.assertIn('y/n', option['description'])
        self.assertEqual(option['choices'], [
            {'name': 'y', 'value': 'y'},
            {'name': 'n', 'value': 'n'},
        ])
        await command.callback(command.binding, self.owner)
        room = self.service.rooms[10]
        await room.join(self.guest)
        await room.start(self.guest)
        self.assertIsNone(room.answer)
        lobby_timer = room.timer
        self.owner.delete_original_response.reset_mock()
        with patch('chatbot_core.number_baseball.random.SystemRandom.sample', return_value=list('0372')):
            await room.view.start.callback(self.owner)
        self.owner.delete_original_response.assert_awaited_once()
        self.owner.edit_original_response.assert_not_awaited()
        self.assertTrue(lobby_timer.cancelling())
        await room.submit(self.owner, 0, '0372')
        self.assertIn('펩시봇(1턴)', room.embed().description)
        self.assertEqual(room.embed().description.splitlines()[1], '# ????')
        self.assertNotIn('0372', room.embed().description)

        await room.submit(self.guest, 0, '0037')
        self.assertEqual(len(room.players[2].guesses), 0)
        await room.submit(self.guest, 0, '1037')
        await room.submit(self.guest, 0, '1037')
        self.assertEqual(len(room.players[2].guesses), 1)
        for turn in range(1, 9):
            await room.submit(self.guest, turn, '1037')
        edited = self.message.edit.call_args.kwargs
        self.assertIn('참가자(실패)', edited['embed'].description)
        self.assertEqual(edited['embed'].description.splitlines()[1], '# 0372')
        self.assertIsNone(edited['view'])
        self.assertNotIn(10, self.service.rooms)
        result = self.guest.edit_original_response.call_args.kwargs
        self.assertIn('0S 3B', result['embed'].description)
        self.assertEqual(result['embed'].title, '숫자야구 내 결과 (9/9턴)')
        self.assertIsNone(result['view'])

    async def test_duplicate_room_auto_starts_and_accepts_repeated_digits(self):
        with patch('chatbot_core.number_baseball.LOBBY_SECONDS', 0):
            await self.service.create(self.owner, 'y')
        room = self.service.rooms[10]
        with patch('chatbot_core.number_baseball.random.SystemRandom.choices', return_value=list('1977')):
            await asyncio.wait_for(room.timer, timeout=1)
        await room.submit(self.owner, 0, '1179')
        result = self.owner.edit_original_response.call_args.kwargs
        self.assertEqual(result['embed'].title, '숫자야구 내 결과 (1/9턴)')
        self.assertIn('### `| TURN | GUESS   | RESULT`\n'
                      '### `| 01   | 1 1 7 9 | 2S 1B`', result['embed'].description)
        personal_view = result['view']
        self.assertEqual([item.label for item in personal_view.children], ['숫자 입력'])
        self.assertIn('????', room.embed().description)

        await personal_view.guess.callback(self.owner)
        modal = self.owner.response.send_modal.call_args.args[0]
        modal.guess._value = 'ABCD'
        submission = interaction(self.owner.user)
        await modal.on_submit(submission)
        submission.followup.send.assert_awaited_once()
        submission.edit_original_response.assert_not_awaited()

        await personal_view.guess.callback(self.owner)
        modal = self.owner.response.send_modal.call_args.args[0]
        modal.guess._value = '1177'
        submission = interaction(self.owner.user)
        await modal.on_submit(submission)
        result = submission.edit_original_response.call_args.kwargs
        self.assertIn('3S 0B', result['embed'].description)
        self.assertEqual(result['embed'].title, '숫자야구 내 결과 (2/9턴)')
        self.assertIs(result['view'], personal_view)

        await personal_view.guess.callback(self.owner)
        modal = self.owner.response.send_modal.call_args.args[0]
        modal.guess._value = '1977'
        submission = interaction(self.owner.user)
        await modal.on_submit(submission)
        submission.response.defer.assert_awaited_once_with(ephemeral=False, thinking=False)
        result = submission.edit_original_response.call_args.kwargs
        self.assertIn('2S 1B', result['embed'].description)
        self.assertIn('4S 0B', result['embed'].description)
        self.assertIsNone(result['view'])
        self.assertIn('펩시봇(3턴)', room.embed().description)
        self.assertIn('1977', room.embed().description)

    async def test_timeout_keeps_success_and_fails_unfinished_players(self):
        await self.service.create(self.owner)
        room = self.service.rooms[10]
        await room.join(self.guest)
        with patch('chatbot_core.number_baseball.random.SystemRandom.sample', return_value=list('0372')):
            await room.start(self.owner)
        await room.submit(self.owner, 0, '0372')
        await room.submit(self.guest, 0, '1234')

        room.timer.cancel()
        await asyncio.gather(room.timer, return_exceptions=True)
        room.deadline = asyncio.get_running_loop().time()
        await room.submit(self.guest, 1, '0372')
        self.assertIn('제한 시간', self.guest.edit_original_response.call_args.kwargs['content'])
        await room.auto_finish()

        edited = self.message.edit.call_args.kwargs
        self.assertIn('펩시봇(1턴)', edited['embed'].description)
        self.assertIn('참가자(실패)', edited['embed'].description)
        self.assertIn('\n# 0372', edited['embed'].description)
        self.assertIsNone(edited['view'])
        self.assertNotIn(10, self.service.rooms)

    async def test_only_owner_can_end_a_running_game(self):
        await self.service.create(self.owner)
        room = self.service.rooms[10]
        await room.join(self.guest)
        with patch('chatbot_core.number_baseball.random.SystemRandom.sample', return_value=list('9305')):
            await room.start(self.owner)
        await room.view.end.callback(self.guest)
        self.guest.response.send_message.assert_awaited_once_with(
            '방장만 게임을 종료할 수 있습니다.', ephemeral=True
        )
        self.assertTrue(room.active)
        await room.submit(self.owner, 0, '9305')
        await room.view.end.callback(self.owner)

        edited = self.message.edit.call_args.kwargs
        self.assertIn('펩시봇(1턴)', edited['embed'].description)
        self.assertIn('참가자(실패)', edited['embed'].description)
        self.assertIn('\n# 9305', edited['embed'].description)
        self.assertIsNone(edited['view'])
        self.assertFalse(room.active)
        self.assertTrue(room.timer.cancelling())

    async def test_owner_can_close_lobby_before_start(self):
        await self.service.create(self.owner)
        room = self.service.rooms[10]
        await room.view.end.callback(self.owner)
        edited = self.message.edit.call_args.kwargs
        self.assertIn('종료', edited['embed'].description)
        self.assertNotIn('????', edited['embed'].description)
        self.assertIsNone(edited['view'])
        self.assertFalse(room.active)

    async def test_public_guess_button_only_opens_for_participants(self):
        await self.service.create(self.owner)
        room = self.service.rooms[10]
        await room.view.start.callback(self.owner)

        await room.view.guess.callback(self.guest)
        self.guest.response.send_message.assert_awaited_once_with(
            '이 방에 참가한 사람만 숫자를 입력할 수 있습니다.', ephemeral=True
        )
        self.guest.response.send_modal.assert_not_awaited()
        self.assertNotIn(self.guest.user.id, room.players)

        await room.view.guess.callback(self.owner)
        self.owner.response.send_modal.assert_awaited_once()
