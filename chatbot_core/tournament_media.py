"""Horizontal battle cards, with client-side 300 ms damage animation."""
from functools import lru_cache
from io import BytesIO
import os
from pathlib import Path
import copy

from PIL import Image, ImageDraw, ImageFont

from .tournament import START_HP, Tournament
from .tournament_bracket import bracket_forest

BACKGROUND = '#171c24'
GREEN = '#47cf83'
RED = '#f0646c'
GRAY = '#7f8998'
ROLL_FRAME_MS = 300
DAMAGE_FRAME_MS = 300
RESULT_HOLD_MS = 1500
TURN_SECONDS = (3 * ROLL_FRAME_MS + RESULT_HOLD_MS) / 1000


@lru_cache(maxsize=24)
def font(size):
    candidates = [Path(os.getenv('WINDIR', 'C:/Windows')) / 'Fonts/malgun.ttf',
                  Path('/system/fonts/NotoSansCJK-Regular.ttc'),
                  Path('/system/fonts/NotoSansCJK-VF.ttc'),
                  Path('/system/fonts/NotoSansKR-Regular.ttf'),
                  Path('/system/fonts/NotoSansCJK-Regular.otf')]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def fitted_name(draw, name, center):
    name = ' '.join(name.split())
    for size in range(30, 15, -2):
        face = font(size)
        if draw.textlength(name, font=face) <= 300:
            break
    while draw.textlength(name, font=face) > 300 and len(name) > 1:
        name = name[:-2] + '…'
    draw.text((center, 32), name, font=face, fill='#f1f4f8', anchor='mm')


def draw_die(draw, center, value):
    left, top = center - 32, 68
    draw.rounded_rectangle((left, top, left + 64, top + 64), radius=12, fill='#f1f4f8')
    if value is None:
        draw.text((center, top + 31), '?', font=font(38), fill=BACKGROUND, anchor='mm')
        return
    patterns = {1: [(1, 1)], 2: [(0, 0), (2, 2)], 3: [(0, 0), (1, 1), (2, 2)],
                4: [(0, 0), (2, 0), (0, 2), (2, 2)],
                5: [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)],
                6: [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)]}
    for x, y in patterns.get(value, []):
        px, py = left + 16 + x * 16, top + 16 + y * 16
        draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=BACKGROUND)


def battle_frame(room, rolling=0, phase='empty'):
    match = room.data['current']
    image = Image.new('RGB', (720, 262), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((360, 100), 'VS', font=font(28), fill='#98a5b7', anchor='mm')
    if rolling:
        countdown = 3 if rolling is True else rolling
        draw.text((360, 168), str(countdown), font=font(34), fill='#ffd166', anchor='mm')
    before = match.get('hp_before', match['hp'])
    for index, uid in enumerate((match['a'], match['b'])):
        center = 180 + 360 * index
        fitted_name(draw, room.name(uid), center)
        value = None if rolling or not match['dice'] else match['dice'][index]
        draw_die(draw, center, value)
        hp = match['hp'][index]
        shown_hp = before[index] if phase == 'green' and not rolling else hp
        draw.text((center, 184), f'HP {shown_hp} / {START_HP}', font=font(22), fill='#e4eaf2', anchor='mm')
        for cell in range(START_HP):
            color = GREEN if cell < hp else None
            if hp <= cell < before[index] and not rolling:
                color = {'green': GREEN, 'red': RED, 'gray': GRAY}.get(phase)
            if color:
                x = center - 93 + cell * 32
                draw.rectangle((x, 218, x + 25, 243), fill=color)
    return image


def battle_media(room, rolling=0, animate=False):
    match = room.data['current']
    animated = animate and not rolling and match.get('hp_before', match['hp']) != match['hp']
    output = BytesIO()
    if animated:
        frames = [battle_frame(room, phase=phase) for phase in ('green', 'red', 'gray', 'empty')]
        # No loop extension: play once, then leave the empty damaged slots shown.
        frames[0].save(output, format='GIF', save_all=True, append_images=frames[1:],
                       duration=300, disposal=2, optimize=False)
        suffix = 'damage.gif'
    else:
        battle_frame(room, rolling=rolling).save(output, format='PNG')
        suffix = 'rolling.png' if rolling else 'result.png'
    filename = f"battle-{room.data['message']}-{match.get('match_index', 0)}-{match['turn']}-{suffix}"
    return filename, output.getvalue()


def match_media(data):
    """One upload for rolling dice and every HP transition in a whole match."""
    preview = Tournament.restore(copy.deepcopy(data))
    match = preview.data['current']
    plan = match.pop('animation_plan')
    rolls = plan['rolls'][plan['cursor']:]
    frames, durations = [], []

    def append(frame, duration):
        # Indexed frames bound memory on Android, even for a long tie sequence.
        frames.append(frame.quantize(colors=128, method=Image.Quantize.FASTOCTREE))
        durations.append(duration)

    for dice in rolls:
        for countdown in (3, 2, 1):
            append(battle_frame(preview, rolling=countdown), ROLL_FRAME_MS)
        preview.roll(dice)
        for phase, duration in [('green', DAMAGE_FRAME_MS), ('red', DAMAGE_FRAME_MS),
                                ('gray', DAMAGE_FRAME_MS), ('empty', RESULT_HOLD_MS - 3 * DAMAGE_FRAME_MS)]:
            append(battle_frame(preview, phase=phase), duration)
    if not frames:
        raise ValueError('재생할 경기 진행 정보가 없습니다.')
    output = BytesIO()
    frames[0].save(output, format='GIF', save_all=True, append_images=frames[1:],
                   duration=durations, disposal=2, optimize=False)
    payload = output.getvalue()
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError('경기 애니메이션 용량이 너무 큽니다.')
    filename = f"match-{data['message']}-{match.get('match_index', 0)}-{match['turn']}.gif"
    return filename, payload


def bracket_media(data):
    """Render every assigned match into a single scalable PNG, without pages."""
    labels, roots, byes = bracket_forest(data)

    def measure(node):
        if not node.get('children'):
            return 1, 0
        parts = [measure(child) for child in node['children']]
        return sum(p[0] for p in parts), 1 + max(p[1] for p in parts)

    sizes = [measure(root) for root in roots]
    canvas_width = max(720, min(8192, max((leaves for leaves, _ in sizes), default=1) * 110 + 80))
    section_heights = [depth * 100 + 130 for _, depth in sizes]
    canvas_height = 90 + sum(section_heights) + (70 + len(byes) * 34 if byes else 0)
    canvas_height = max(200, canvas_height)
    image = Image.new('RGB', (canvas_width, canvas_height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((40, 20), '주작 대진표', font=font(32), fill='#f1f4f8')
    draw.text((canvas_width - 40, 40), f"참가 {len(data['players'])}명", font=font(22),
              fill='#98a5b7', anchor='rm')
    top = 90
    if not roots:
        draw.text((40, 110), '경기를 시작하면 대진이 표시됩니다.', font=font(26), fill='#98a5b7')

    for root, (leaves, depth), height in zip(roots, sizes, section_heights):
        draw.text((40, top), root['stage'], font=font(26), fill='#47cf83')
        gap = min(110, (canvas_width - 80) / leaves)
        start = (canvas_width - leaves * gap) / 2
        face = font(max(9, min(28, int(gap / 3.6))))
        cursor = 0

        def layout(node, level):
            nonlocal cursor
            if not node.get('children'):
                x = start + (cursor + 0.5) * gap
                cursor += 1
                return dict(x=x, y=top + 60 + depth * 100, node=node, children=[])
            children = [layout(child, level + 1) for child in node['children']]
            return dict(x=sum(child['x'] for child in children) / len(children),
                        y=top + 60 + level * 100, node=node, children=children)

        def paint(item):
            x, y, node, children = item['x'], item['y'], item['node'], item['children']
            if children:
                branch_y = y + 50
                draw.line((x, y + 20, x, branch_y), fill='#98a5b7', width=2)
                draw.line((children[0]['x'], branch_y, children[1]['x'], branch_y), fill='#98a5b7', width=2)
                for child in children:
                    draw.line((child['x'], branch_y, child['x'], child['y'] - 20), fill='#98a5b7', width=2)
                    paint(child)
            uid = node.get('winner') or node.get('user')
            text = labels.get(uid, '?') if uid else '대기'
            color = '#ffd166' if node is root and root['stage'] == '결승전' and uid else '#f1f4f8'
            draw.text((x, y), text, font=face, fill=color, anchor='mm')

        paint(layout(root, 0))
        top += height
    if byes:
        draw.text((40, top), '부전승', font=font(26), fill='#47cf83')
        for line in byes:
            top += 34
            draw.text((40, top), line, font=font(22), fill='#c1cad7')
    output = BytesIO()
    image.save(output, format='PNG')
    return f"bracket-{data['message']}.png", output.getvalue()
