from io import BytesIO
import unittest

from PIL import Image, ImageColor

from chatbot_core.tournament import Tournament
from chatbot_core.tournament_media import battle_media, match_media, BACKGROUND, GREEN, RED, GRAY


class MediaTests(unittest.TestCase):
    def room(self):
        room = Tournament(1, '테스트', 10, 20)
        for uid in range(1, 5):
            room.add(uid, f'참가자{uid}')
        room.start()
        return room

    def test_damage_animation_has_four_300ms_frames_without_loop(self):
        room = self.room()
        room.roll((1, 5))
        name, data = battle_media(room, animate=True)
        self.assertTrue(name.endswith('damage.gif'))
        image = Image.open(BytesIO(data))
        self.assertEqual(image.n_frames, 4)
        self.assertNotIn('loop', image.info)
        # Left participant loses four HP: cells 2 through 5 change color.
        damaged = (180 - 93 + 2 * 32 + 12, 230)
        remaining = (180 - 93 + 12, 230)
        opponent = (540 - 93 + 5 * 32 + 12, 230)
        for index, color in enumerate((GREEN, RED, GRAY, BACKGROUND)):
            image.seek(index)
            self.assertEqual(image.info['duration'], 300)
            frame = image.convert('RGB')
            self.assertEqual(frame.getpixel(damaged), ImageColor.getrgb(color))
            self.assertEqual(frame.getpixel(remaining), ImageColor.getrgb(GREEN))
            self.assertEqual(frame.getpixel(opponent), ImageColor.getrgb(GREEN))

    def test_countdown_changes_counter_but_keeps_question_mark_dice(self):
        room = self.room()
        room.roll((1, 5))
        name, data = battle_media(room, rolling=3)
        self.assertTrue(name.endswith('rolling.png'))
        image = Image.open(BytesIO(data))
        self.assertEqual(image.format, 'PNG')
        counters = [image.crop((335, 140, 386, 194)).tobytes()]
        for countdown in (2, 1):
            other = Image.open(BytesIO(battle_media(room, rolling=countdown)[1]))
            self.assertEqual(other.crop((148, 68, 213, 133)).tobytes(), image.crop((148, 68, 213, 133)).tobytes())
            self.assertEqual(other.crop((508, 68, 573, 133)).tobytes(), image.crop((508, 68, 573, 133)).tobytes())
            counters.append(other.crop((335, 140, 386, 194)).tobytes())
        self.assertEqual(len(set(counters)), 3)
        room.roll((2, 2))
        name, data = battle_media(room, animate=True)
        self.assertTrue(name.endswith('result.png'))

    def test_whole_match_gif_contains_dice_and_hp_transitions(self):
        import copy
        room = self.room()
        before = copy.deepcopy(room.data)
        plan = room.plan_match(dice_source=lambda: (6, 1))
        self.assertEqual(room.data, before)
        self.assertEqual(plan['rolls'], [[6, 1], [6, 1]])
        room.data['current']['animation_plan'] = plan
        name, payload = match_media(room.data)
        self.assertTrue(name.startswith('match-'))
        image = Image.open(BytesIO(payload))
        self.assertEqual(image.n_frames, 14)
        self.assertNotIn('loop', image.info)
        durations = []
        for index in range(image.n_frames):
            image.seek(index)
            durations.append(image.info['duration'])
        self.assertEqual(durations, ([300] * 6 + [600]) * 2)
        self.assertLess(len(payload), 8 * 1024 * 1024)
        self.assertEqual(room.data['current']['turn'], 0)
        self.assertEqual(room.data['current']['hp'], [6, 6])

    def test_saved_plan_resumes_without_rerolling(self):
        import json
        room = self.room()
        room.data['current']['animation_plan'] = room.plan_match(dice_source=lambda: (6, 1))
        room.roll((6, 1))
        room.data['current']['animation_plan']['cursor'] = 1
        restored = Tournament.restore(json.loads(json.dumps(room.data)))
        _, payload = match_media(restored.data)
        image = Image.open(BytesIO(payload))
        self.assertEqual(image.n_frames, 7)
        self.assertEqual(restored.data['current']['animation_plan']['rolls'], [[6, 1], [6, 1]])


if __name__ == '__main__':
    unittest.main()
