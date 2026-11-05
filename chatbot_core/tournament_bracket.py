"""Small, fixed-width bracket trees suitable for Discord mobile code blocks."""
import re
import unicodedata


def recover_matches(logs, players):
    """Read pre-bracket save files without changing their existing match logs."""
    ids = {}
    for uid, name in players.items():
        ids.setdefault(name, []).append(uid)
    matches = []
    for line in logs:
        header = re.fullmatch(r'(본선 \d+라운드|준결승|패자부활전|3·4위전|결승전) · (.+) vs (.+)', line)
        if header:
            stage, a, b = header.groups()
            matches.append(dict(stage=stage, a=ids.get(a, [a])[0], b=ids.get(b, [b])[-1], winner=None))
        elif matches and line.endswith(' 승리'):
            match = matches[-1]
            name = line[:-3]
            a, b = match['a'], match['b']
            if players.get(a, a) == name:
                match['winner'] = a
            elif players.get(b, b) == name:
                match['winner'] = b
    return matches


def short_names(players):
    labels, used = {}, set()
    for uid, name in players.items():
        clean = ''.join(c for c in unicodedata.normalize('NFC', name)
                        if not unicodedata.category(c).startswith(('C', 'M')) and c not in '`')
        clean = ' '.join(clean.split()) or '참가자'
        base = clean[:3]
        label, number = base, 1
        while label in used:
            suffix = str(number)
            label = base[:max(0, 3 - len(suffix))] + suffix
            number += 1
        labels[uid] = label
        used.add(label)
    return labels


def width(char):
    return 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1


def draw_tree(node, labels):
    rows = [[' '] * 41 for _ in range(5)]
    truncated = []

    def place(text, y, center):
        x = center - sum(width(c) for c in text) // 2
        for char in text:
            rows[y][x] = char
            if width(char) == 2:
                rows[y][x + 1] = ''
            x += width(char)

    def draw(item, depth, center, step):
        value = item.get('winner') or item.get('user')
        place(labels.get(value, '?') if value else '?', depth * 2, center)
        children = item.get('children')
        if not children:
            return
        if depth == 2:
            truncated.append(item)
            return
        left, right = center - step, center + step
        for x in range(left, right + 1):
            rows[depth * 2 + 1][x] = '─'
        rows[depth * 2 + 1][left] = '┌'
        rows[depth * 2 + 1][center] = '┴'
        rows[depth * 2 + 1][right] = '┐'
        draw(children[0], depth + 1, left, step // 2)
        draw(children[1], depth + 1, right, step // 2)

    draw(node, 0, 20, 10)
    rendered = [ ''.join(row).rstrip() for row in rows ]
    while rendered and not rendered[-1]:
        rendered.pop()
    return '\n'.join(rendered), truncated


def bracket_forest(data):
    players = data['players']
    labels = short_names(players)
    matches = data.get('matches')
    if matches is None:
        matches = recover_matches(data['logs'], players)
    matches = [dict(match) for match in matches]
    # Include assigned matches which have not started yet.
    for a, b in data.get('pending', []):
        matches.append(dict(a=a, b=b, winner=None, stage=data['stage']))
    if not matches:
        return labels, [], []
    latest, nodes, parents = {}, [], set()
    for match in matches:
        children = []
        for user in (match['a'], match['b']):
            child = latest.get(user, dict(user=user))
            if 'index' in child:
                parents.add(child['index'])
            children.append(child)
        node = dict(index=len(nodes), children=children, winner=match['winner'], stage=match['stage'])
        nodes.append(node)
        if match['winner']:
            latest[match['winner']] = node
            loser = match['b'] if match['winner'] == match['a'] else match['a']
            latest.pop(loser, None)
    # Main final first, bronze bracket separately, then earlier unfinished trees.
    roots = [node for node in reversed(nodes) if node['index'] not in parents]
    byes = []
    for line in data['logs']:
        bye = re.fullmatch(r'(.+) · (.+) 부전승', line)
        if bye:
            uid = next((uid for uid, name in players.items() if name == bye[2]), None)
            byes.append(f'{bye[1]} · {labels.get(uid, bye[2][:3])} 부전승')
    return labels, roots, byes


def bracket_pages(data):
    """Text snapshots for diagnostics; the Discord UI uses one full image."""
    labels, roots, byes = bracket_forest(data)
    if not roots:
        return [['시작하면 라운드별 대진을 확인할 수 있습니다.']]
    pages, seen = [], set()
    queue = roots[:]
    while queue:
        node = queue.pop(0)
        if node['index'] in seen:
            continue
        seen.add(node['index'])
        tree, earlier = draw_tree(node, labels)
        pages.append([node['stage'], '```\n' + tree + '\n```'])
        queue.extend(earlier)
    for offset in range(0, len(byes), 10):
        pages.append(['부전승', *byes[offset:offset + 10]])
    return pages
