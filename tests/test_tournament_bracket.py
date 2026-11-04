import json
from io import BytesIO
import unittest
from PIL import Image

from chatbot_core.tournament import Tournament
from chatbot_core.tournament_bracket import bracket_pages, short_names, width
from chatbot_core.tournament_media import bracket_media


def finish(count):
    room = Tournament(1, '테스트', 10, 20)
    for uid in range(1, count + 1):
        room.add(uid, f'참가자{uid}')
    room.start()
    while room.data['status'] != '종료':
        room.roll((6, 1))
        if room.roll((6, 1)):
            room.next_match()
    return room


class BracketTests(unittest.TestCase):
    def test_final_tree_is_above_two_semifinals_and_bronze_is_separate(self):
        data = dict(players={'1': '철수님', '2': '영희님', '3': '민수님', '4': '지수님'},
                    logs=[], pending=[], stage='결승전', matches=[
                        dict(a='1', b='2', winner='1', stage='준결승'),
                        dict(a='3', b='4', winner='4', stage='준결승'),
                        dict(a='2', b='3', winner='2', stage='3·4위전'),
                        dict(a='1', b='4', winner='1', stage='결승전')])
        pages = bracket_pages(data)
        self.assertEqual(pages[0][0], '결승전')
        self.assertEqual(pages[1][0], '3·4위전')
        tree = pages[0][1].splitlines()[1:-1]
        self.assertEqual(tree[0].strip(), '철수님')
        self.assertIn('철수님', tree[2])
        self.assertIn('지수님', tree[2])
        for name in data['players'].values():
            self.assertIn(name, tree[4])
        self.assertEqual(tree[1].strip(), '┌─────────┴─────────┐')
        data['message'] = 999
        filename, content = bracket_media(data)
        self.assertTrue(filename.endswith('.png'))
        image = Image.open(BytesIO(content))
        self.assertEqual(image.size, (720, 650))
        self.assertEqual(image.getpixel((360, 200)), (152, 165, 183))
        self.assertEqual(image.getpixel((250, 220)), (152, 165, 183))

    def test_short_labels_are_unique_and_at_most_three_characters(self):
        players = {str(uid): '똑같은닉네임' for uid in range(128)}
        labels = short_names(players)
        self.assertEqual(len(set(labels.values())), 128)
        self.assertTrue(all(len(label) <= 3 for label in labels.values()))

    def test_large_brackets_revival_byes_and_save_roundtrip(self):
        for count in (4, 5, 6, 8, 17, 128):
            with self.subTest(count=count):
                room = finish(count)
                restored = Tournament.restore(json.loads(json.dumps(room.data)))
                pages = bracket_pages(restored.data)
                self.assertEqual(pages[0][0], '결승전')
                self.assertIn('3·4위전', [page[0] for page in pages])
                if count in (5, 6):
                    self.assertIn('패자부활전', [page[0] for page in pages])
                for page in pages:
                    for text in page:
                        if text.startswith('```'):
                            for row in text.splitlines()[1:-1]:
                                self.assertLessEqual(sum(width(c) for c in row), 41)
                filename, content = bracket_media(restored.data)
                image = Image.open(BytesIO(content))
                self.assertLessEqual(image.width, 8192)
                self.assertLess(len(content), 8 * 1024 * 1024)

    def test_pending_and_legacy_save(self):
        room = Tournament(1, '테스트', 10, 20)
        for uid in range(1, 9):
            room.add(uid, f'참가{uid}')
        room.start()
        text = '\n'.join('\n'.join(page) for page in bracket_pages(room.data))
        labels = short_names(room.data['players'])
        for label in labels.values():
            self.assertIn(label, text)
        legacy = finish(5).data
        legacy.pop('matches')
        restored = Tournament.restore(legacy)
        self.assertTrue(restored.data['matches'])
        self.assertEqual(bracket_pages(restored.data)[0][0], '결승전')


if __name__ == '__main__':
    unittest.main()
