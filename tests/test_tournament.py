import asyncio
import json
import queue
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from chatbot_core import Bridge
from chatbot_core.tournament import Tournament
from chatbot_core.tournament_discord import RoomView, PageView, battle_pages


def make_room(count):
    room = Tournament(1, '테스트', 10, 20)
    for i in range(count):
        room.add(i + 1, f'참가자{i + 1}')
    return room


class EngineTests(unittest.TestCase):
    def test_battle_history_is_compact_and_separate_per_match(self):
        logs = ['본선 1라운드 · 대기자 부전승', '준결승 · 사용자1 vs 사용자2',
                '사용자1 1:5 사용자2 · HP 2:6', '사용자1 1:5 사용자2 · HP 0:6', '사용자2 승리',
                '준결승 · 사용자3 vs 사용자4', '사용자3 3:3 사용자4 · HP 6:6',
                '사용자3 6:1 사용자4 · HP 6:1']
        pages = battle_pages(logs)
        self.assertEqual(pages[0], ['사용자1 VS 사용자2', '    1  :  5  => 사용자1 HP-4',
                                    '    1  :  5  => 사용자1 HP-4', '사용자2 승리'])
        self.assertEqual(pages[1], ['사용자3 VS 사용자4', '    3  :  3  => 피해 없음',
                                    '    6  :  1  => 사용자4 HP-5'])
        long_pages = battle_pages(['결승전 · 사용자1 vs 사용자2'] +
                                 ['사용자1 3:3 사용자2 · HP 6:6'] * 1000 + ['사용자1 승리'])
        self.assertGreater(len(long_pages), 1)
        self.assertTrue(all(p[0] == '사용자1 VS 사용자2' for p in long_pages))
        self.assertEqual(long_pages[-1][-1], '사용자1 승리')
        for index in range(len(long_pages)):
            self.assertLessEqual(len(PageView.page(long_pages, index).description), 4096)

    def test_all_participant_counts_finish_with_unique_complete_rankings(self):
        for count in range(4, 129):
            with self.subTest(count=count):
                room = make_room(count)
                room.start()
                phases = []
                for _ in range(3000):
                    if room.data['status'] == '종료':
                        break
                    phases.append(room.data['stage'])
                    self.assertEqual(room.data['current']['hp'], [6, 6])
                    self.assertFalse(room.roll((6, 1)))
                    self.assertTrue(room.roll((6, 1)))
                    # Resume from a JSON save after every completed match.
                    room = Tournament.restore(json.loads(json.dumps(room.data)))
                    room.next_match()
                self.assertEqual(room.data['status'], '종료')
                ranks = room.standings()
                self.assertEqual([len(g) for g in ranks[:4]], [1, 1, 1, 1])
                flat = [p for group in ranks for p in group]
                self.assertEqual(len(flat), count)
                self.assertEqual(set(flat), set(room.data['players']))
                self.assertLess(phases.index('3·4위전'), phases.index('결승전'))

    def test_damage_tie_and_hp_reset(self):
        room = make_room(4)
        room.start()
        room.roll((3, 3))
        self.assertEqual(room.data['current']['hp'], [6, 6])
        room.roll((2, 6))
        self.assertEqual(room.data['current']['hp'], [2, 6])
        room.roll((2, 3))
        self.assertEqual(room.data['current']['hp'], [1, 6])
        self.assertTrue(room.roll((1, 6)))
        self.assertEqual(room.data['current']['hp'], [0, 6])
        room.next_match()
        self.assertEqual(room.data['current']['hp'], [6, 6])

    def test_previous_hp10_save_preserves_damage_at_hp6(self):
        room = make_room(4)
        room.start()
        old = json.loads(json.dumps(room.data))
        old.pop('max_hp')
        old['current']['hp'] = [8, 10]
        restored = Tournament.restore(old)
        self.assertEqual(restored.data['current']['hp'], [4, 6])
        self.assertEqual(restored.data['max_hp'], 6)

    def test_revival_before_semifinals(self):
        room = make_room(5)
        room.start()
        while room.data['stage'] != '패자부활전':
            room.roll((6, 1))
            if room.roll((6, 1)):
                room.next_match()
        self.assertEqual(len(room.data['alive']), 3)
        self.assertEqual(len(room.data['qualifiers']), 2)
        room.roll((6, 1))
        room.roll((6, 1))
        room.next_match()
        self.assertEqual(room.data['stage'], '준결승')
        self.assertEqual(len(room.data['alive']), 4)

    def test_membership_lock_and_minimum(self):
        room = make_room(3)
        with self.assertRaises(ValueError):
            room.start()
        with self.assertRaises(ValueError):
            room.add(1, '중복')
        room.add(4, '네번째')
        room.start()
        with self.assertRaises(ValueError):
            room.remove(1)
        with self.assertRaises(ValueError):
            room.add(5, '늦은 참가')


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = Bridge(queue.Queue(), self.temp.name)
        self.bridge._connection.user = type('User', (), {'id': 123})()
        self.service = self.bridge.tournaments
        self.service.tree.sync = AsyncMock()
        await self.service.setup()

    async def asyncTearDown(self):
        await self.service.close()
        self.temp.cleanup()

    async def test_help_lists_registered_commands_privately(self):
        interaction = type('Interaction', (), {})()
        interaction.response = type('Response', (), {'send_message': AsyncMock()})()
        command = self.service.tree.get_command('펩시봇')
        self.assertIsNotNone(command)
        self.assertIs(command.binding, self.service)
        await command.callback(command.binding, interaction)
        result = interaction.response.send_message.call_args.kwargs
        self.assertTrue(result['ephemeral'])
        for name in ('펩시봇', '주작기 시작', '주작기 종료', '주작기 참가'):
            self.assertIn('/' + name, result['embed'].description)
        self.assertEqual(len(result['embed'].fields), 0)
        for name in ('추첨생성', '추첨종료', '참가'):
            self.assertIsNone(self.service.tree.get_command(name))
        group = self.service.tree.get_command('주작기')
        for name, method in [('시작', 'create'), ('종료', 'stop'), ('참가', 'join')]:
            subcommand = group.get_command(name)
            self.assertIs(subcommand.binding, self.service)
            self.assertIs(subcommand.callback, getattr(self.service, method).__func__)
        schema = group.to_dict(self.service.tree)
        self.assertEqual({option['name'] for option in schema['options']}, {'시작', '종료', '참가'})

    async def test_saved_state_persistent_buttons_and_single_process_lock(self):
        room = make_room(5)
        room.start()
        room.roll((4, 2))
        self.service.rooms['100'] = room
        self.service.save()
        saved = json.loads(self.service.file.read_text(encoding='utf-8'))
        self.assertEqual(saved['100'], room.data)
        self.assertTrue(RoomView(self.service, '100').is_persistent())
        other = Bridge(queue.Queue(), self.temp.name)
        other._connection.user = self.bridge.user
        other.tournaments.tree.sync = AsyncMock()
        await other.tournaments.setup()
        self.assertFalse(other.tournaments.enabled)
        await other.tournaments.close()
        await self.service.close()
        await other.tournaments.setup()
        self.assertTrue(other.tournaments.enabled)
        self.assertEqual(other.tournaments.rooms['100'].data, room.data)
        await other.tournaments.close()

    async def test_non_owner_cannot_manage_or_start(self):
        self.service.rooms['100'] = make_room(4)
        interaction = type('Interaction', (), {})()
        interaction.user = type('User', (), {'id': 999})()
        interaction.response = type('Response', (), {'send_message': AsyncMock()})()
        for action in ('manage', 'start', 'stop', 'add', 'remove'):
            await self.service.action(interaction, '100', action)
        self.assertEqual(interaction.response.send_message.await_count, 5)
        self.assertEqual(self.service.rooms['100'].data['status'], '모집 중')

    async def test_bracket_is_one_private_image_without_page_buttons(self):
        room = make_room(8)
        room.start()
        interaction = type('Interaction', (), {})()
        interaction.response = type('Response', (), {'defer': AsyncMock()})()
        interaction.followup = type('Followup', (), {'send': AsyncMock()})()
        await self.service.details(interaction, room, 'bracket')
        response = interaction.followup.send.call_args.kwargs
        self.assertTrue(response['ephemeral'])
        self.assertEqual(response['embed'].title, '주작 대진표')
        self.assertTrue(response['file'].filename.endswith('.png'))
        self.assertNotIn('view', response)
        self.assertIsNone(response['embed'].description)

    async def test_running_tournament_blocks_only_same_channel_creation(self):
        running = make_room(4)
        running.start()
        self.service.rooms['100'] = running
        waiting = make_room(4)
        waiting.data['channel'] = 88
        self.service.rooms['200'] = waiting
        interaction = type('Interaction', (), {})()
        interaction.guild = object()
        interaction.channel_id = 10
        interaction.user = type('User', (), {'id': 1})()
        interaction.response = type('Response', (), {'defer': AsyncMock()})()
        interaction.followup = type('Followup', (), {'send': AsyncMock()})()
        await self.service.create(interaction)
        self.assertEqual(len(self.service.rooms), 2)
        self.assertIn('진행 중', interaction.followup.send.call_args.args[0])
        interaction.channel_id = 99
        interaction.guild_id = 20
        interaction.id = 300
        interaction.delete_original_response = AsyncMock()
        interaction.channel = type('Channel', (), {'send': AsyncMock(return_value=type('Message', (), {'id': 999})())})()
        await self.service.create(interaction)
        self.assertEqual(len(self.service.rooms), 3)
        self.assertEqual(self.service.rooms['300'].data['channel'], 99)
        with patch.object(self.service, 'edit', new=AsyncMock()), patch.object(self.service, 'launch') as launch:
            await self.service.action(interaction, '200', 'start')
            self.assertEqual(waiting.data['status'], '진행 중')
            launch.assert_called_once_with('200')
        self.assertEqual(running.data['status'], '진행 중')

    def interaction(self, uid=1):
        interaction = type('Interaction', (), {})()
        interaction.user = type('User', (), {'id': uid, 'display_name': '새참가', 'bot': False})()
        interaction.response = type('Response', (), {'defer': AsyncMock()})()
        interaction.followup = type('Followup', (), {'send': AsyncMock()})()
        interaction.delete_original_response = AsyncMock()
        return interaction

    async def test_start_button_acknowledges_silently_without_waiting_for_image(self):
        room = make_room(4)
        self.service.rooms['100'] = room
        interaction = self.interaction()
        with patch.object(self.service, 'edit', new=AsyncMock()) as edit, \
             patch.object(self.service, 'launch') as launch:
            await self.service.action(interaction, '100', 'start')
        self.assertEqual(room.data['status'], '진행 중')
        interaction.response.defer.assert_awaited_once_with(thinking=False)
        interaction.followup.send.assert_not_awaited()
        edit.assert_not_awaited()
        launch.assert_called_once_with('100')

    async def test_unexpected_start_error_is_private_and_diagnostics_exclude_secrets(self):
        room = make_room(4)
        self.service.rooms['100'] = room
        interaction = self.interaction()
        with patch.object(room, 'start', side_effect=RuntimeError('secret-value-must-not-be-logged')):
            await self.service.action(interaction, '100', 'start')
        self.assertIn('RuntimeError', interaction.followup.send.call_args.args[0])
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        log = (self.service.root / 'tournament-errors.log').read_text(encoding='utf-8')
        self.assertIn('RuntimeError', log)
        self.assertNotIn('secret-value', log)

    async def test_start_reports_missing_attach_files_before_state_change(self):
        room = make_room(4)
        self.service.rooms['100'] = room
        interaction = self.interaction()
        permissions = type('Permissions', (), dict(view_channel=True, send_messages=True,
                                                   embed_links=True, attach_files=False))()
        channel = type('Channel', (), {'permissions_for': lambda _, member: permissions})()
        guild = type('Guild', (), {'me': object()})()
        with patch.object(self.bridge, 'get_guild', return_value=guild), \
             patch.object(self.bridge, 'get_channel', return_value=channel):
            await self.service.action(interaction, '100', 'start')
        self.assertEqual(room.data['status'], '모집 중')
        self.assertIn('파일 첨부', interaction.followup.send.call_args.args[0])

    async def test_successful_slash_join_deletes_thinking_response(self):
        import discord
        self.service.rooms['100'] = make_room(4)
        interaction = self.interaction(50)
        interaction.type = discord.InteractionType.application_command
        with patch.object(self.service, 'edit', new=AsyncMock()):
            await self.service.action(interaction, '100', 'join')
        interaction.delete_original_response.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()

    async def test_runner_reports_unexpected_error_on_existing_card(self):
        room = make_room(4)
        room.start()
        self.service.rooms['100'] = room
        self.bridge.wait_until_ready = AsyncMock()
        with patch.object(self.service, 'edit', new=AsyncMock(side_effect=[RuntimeError('test-error'), None])) as edit:
            await self.service.run('100')
        self.assertIn('RuntimeError', room.data['error'])
        self.assertEqual(edit.await_count, 2)
        self.assertIn('진행을 중단', self.service.embed(room).description)

    async def test_embed_limits_and_full_ranking_pages(self):
        room = make_room(128)
        room.data['players'] = {k: '긴이름_*' * 13 for k in room.data['players']}
        embed = self.service.embed(room)
        self.assertLessEqual(len(embed), 6000)
        room.start()
        while room.data['status'] != '종료':
            room.roll((6, 1))
            if room.roll((6, 1)):
                room.next_match()
        self.assertLessEqual(len(self.service.embed(room)), 6000)

    async def test_lobby_lists_every_participant_horizontally(self):
        room = make_room(128)
        room.data['players'] = {str(10000000000000000000 + i): '아주 긴 닉네임 ' * 7 for i in range(128)}
        embed = self.service.embed(room)
        listing = embed.description.split('\n')[1]
        self.assertEqual(listing, ' · '.join(f'<@{uid}>' for uid in room.data['players']))
        self.assertNotIn('외 ', embed.description)
        self.assertIn('❤️ HP 6', embed.description)
        self.assertNotIn('매 경기', embed.description)
        self.assertLessEqual(len(embed.description), 4096)
        self.assertLessEqual(len(embed), 6000)

    async def test_runner_edits_one_message_and_finishes_after_resume(self):
        room = make_room(5)
        room.data['message'] = 999
        room.start()
        room.roll((6, 1))
        room.roll((6, 1))  # Resume a finished match before its transition.
        self.service.rooms['100'] = room
        self.bridge.wait_until_ready = AsyncMock()
        message = type('Message', (), {'edit': AsyncMock(return_value=None)})()
        channel = type('Channel', (), {'get_partial_message': lambda _, mid: message})()
        with patch.object(self.bridge, 'get_channel', return_value=channel), \
             patch.object(self.service, 'wait_animation', new=AsyncMock()) as wait:
            original_plan = room.plan_match
            room.plan_match = lambda: original_plan(dice_source=lambda: (6, 1))
            await self.service.run('100')
        self.assertEqual(room.data['status'], '종료')
        first_frame = message.edit.call_args_list[0].kwargs['embed']
        self.assertIn('match-', first_frame.image.url)
        self.assertTrue(first_frame.image.url.endswith('.gif'))
        deadlines = [call.args[0] for call in wait.await_args_list[:2]]
        self.assertAlmostEqual(deadlines[1] - deadlines[0], 1.5)
        uploads = [call for call in message.edit.call_args_list if call.kwargs.get('attachments')]
        # The first match was already finished in the restored state.
        self.assertEqual(len(uploads), len(room.data['matches']) - 1)
        self.assertEqual(message.edit.await_count, len(uploads) + 1)
        for call in uploads:
            embed = call.kwargs['embed']
            self.assertIn(' VS ', embed.description)
            self.assertNotIn('굴리는 중', embed.description)
            self.assertEqual(len(embed.fields), 0)
        self.assertIn('최종 결과', message.edit.call_args.kwargs['embed'].description)
        saved = json.loads(self.service.file.read_text(encoding='utf-8'))
        self.assertEqual(saved['100']['status'], '종료')

    async def test_live_card_hides_roll_records_but_history_button_reads_them(self):
        room = make_room(4)
        room.start()
        room.roll((6, 1))
        embed = self.service.embed(room)
        self.assertEqual(len(embed.fields), 0)
        self.assertNotIn('HP', embed.description)
        self.assertNotIn('턴', embed.description)
        interaction = type('Interaction', (), {})()
        interaction.response = type('Response', (), {'send_message': AsyncMock()})()
        await self.service.details(interaction, room, 'history')
        response = interaction.response.send_message.call_args.kwargs
        self.assertTrue(response['ephemeral'])
        self.assertIn('6  :  1', response['embed'].description)
        self.assertIn('HP-5', response['embed'].description)

    async def test_save_failure_rolls_back_membership(self):
        room = make_room(4)
        self.service.rooms['100'] = room
        interaction = type('Interaction', (), {})()
        interaction.user = type('User', (), {'id': 50, 'display_name': '새참가', 'bot': False})()
        interaction.response = type('Response', (), {'defer': AsyncMock()})()
        interaction.followup = type('Followup', (), {'send': AsyncMock()})()
        with patch.object(self.service, 'save', side_effect=OSError('disk full')):
            await self.service.action(interaction, '100', 'join')
        self.assertNotIn('50', room.data['players'])

    async def test_owner_select_add_remove_and_post_start_lock(self):
        room = make_room(4)
        self.service.rooms['100'] = room
        interaction = type('Interaction', (), {})()
        interaction.user = type('User', (), {'id': 1})()
        interaction.response = type('Response', (), {'defer': AsyncMock()})()
        interaction.followup = type('Followup', (), {'send': AsyncMock()})()
        users = [type('User', (), {'id': 5, 'display_name': '추가', 'bot': False})(),
                 type('User', (), {'id': 6, 'display_name': '봇', 'bot': True})()]
        with patch.object(self.service, 'edit', new=AsyncMock()):
            await self.service.action(interaction, '100', 'add', users)
            self.assertIn('5', room.data['players'])
            self.assertNotIn('6', room.data['players'])
            await self.service.action(interaction, '100', 'remove', users)
            self.assertNotIn('5', room.data['players'])
            room.start()
            await self.service.action(interaction, '100', 'add', users)
            self.assertNotIn('5', room.data['players'])


if __name__ == '__main__':
    unittest.main()
