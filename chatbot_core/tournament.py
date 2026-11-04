"""Serializable dice tournament engine; no Discord or network dependency."""
import random
import copy
from .tournament_bracket import recover_matches

START_HP = 6


class Tournament:
    def __init__(self, owner, title, channel, guild):
        self.data = dict(owner=owner, title=title, channel=channel, guild=guild,
                         message=0, status='모집 중', players={}, alive=[], byes=[],
                         pending=[], winners=[], losers=[], eliminated=[],
                         rankings=[], current=None, stage='본선', round=0, logs=[], max_hp=START_HP, matches=[])

    @classmethod
    def restore(cls, data):
        obj = cls.__new__(cls)
        obj.data = data
        previous_hp = data.get('max_hp', 10)
        if previous_hp != START_HP and data.get('current'):
            data['current']['hp'] = [max(0, min(START_HP, hp - previous_hp + START_HP))
                                     for hp in data['current']['hp']]
        data['max_hp'] = START_HP
        if 'matches' not in data:
            data['matches'] = recover_matches(data['logs'], data['players'])
            current = data.get('current')
            if current:
                if not data['matches']:
                    data['matches'].append(dict(a=current['a'], b=current['b'], winner=None, stage=data['stage']))
                current['match_index'] = len(data['matches']) - 1
                record = data['matches'][-1]
                record.update(a=current['a'], b=current['b'])
                if min(current['hp']) == 0:
                    record['winner'] = current['a'] if current['hp'][1] == 0 else current['b']
        return obj

    def add(self, user_id, name):
        d = self.data
        if d['status'] != '모집 중':
            raise ValueError('모집이 마감되었습니다.')
        if str(user_id) in d['players']:
            raise ValueError('이미 참가한 사용자입니다.')
        if len(d['players']) >= 128:
            raise ValueError('참가자는 최대 128명입니다.')
        d['players'][str(user_id)] = name[:80]

    def remove(self, user_id):
        if self.data['status'] != '모집 중':
            raise ValueError('모집이 마감되었습니다.')
        if self.data['players'].pop(str(user_id), None) is None:
            raise ValueError('참가 명단에 없습니다.')

    def start(self):
        d = self.data
        if d['status'] != '모집 중':
            raise ValueError('이미 시작했거나 종료된 추첨입니다.')
        if len(d['players']) < 4:
            raise ValueError('최소 4명이 참가해야 시작할 수 있습니다.')
        d['status'] = '진행 중'
        d['alive'] = list(d['players'])
        self.new_round()

    def log(self, text):
        self.data['logs'].append(text)

    def new_round(self):
        d = self.data
        d['round'] += 1
        ids = d['alive'][:]
        if len(ids) == 3:
            d['qualifiers'] = d['eliminated'].pop()[:]
            d['stage'] = '패자부활전'
            self.qualifier_round()
            return
        random.SystemRandom().shuffle(ids)
        d['winners'], d['losers'] = [], []
        if len(ids) == 2:
            d['stage'] = '결승전'
            d['pending'] = [ids]
        else:
            d['stage'] = '준결승' if len(ids) == 4 else f"본선 {d['round']}라운드"
            if len(ids) % 2:
                candidates = [p for p in ids if p not in d['byes']] or ids
                bye = random.SystemRandom().choice(candidates)
                ids.remove(bye)
                d['byes'].append(bye)
                d['winners'].append(bye)
                self.log(f"{d['stage']} · {self.name(bye)} 부전승")
            d['pending'] = [ids[i:i + 2] for i in range(0, len(ids), 2)]
        self.next_match()

    def name(self, user_id):
        return self.data['players'].get(str(user_id), '알 수 없음')

    def next_match(self):
        d = self.data
        if d['pending']:
            a, b = d['pending'].pop(0)
            d['matches'].append(dict(a=a, b=b, winner=None, stage=d['stage']))
            d['current'] = dict(a=a, b=b, hp=[START_HP, START_HP], dice=None, turn=0,
                                match_index=len(d['matches']) - 1)
            self.log(f"{d['stage']} · {self.name(a)} vs {self.name(b)}")
            return
        d['current'] = None
        if d['stage'] == '3·4위전':
            d['stage'] = '결승전'
            d['pending'] = [d['alive'][:]]
            self.next_match()
        elif d['stage'] == '결승전':
            d['status'] = '종료'
        elif d['stage'] == '패자부활전':
            self.qualifier_round()
        elif len(d['winners']) == 2:
            d['alive'] = d['winners'][:]
            d['stage'] = '3·4위전'
            d['pending'] = [d['losers'][:]]
            self.next_match()
        else:
            d['eliminated'].append(d['losers'][:])
            d['alive'] = d['winners'][:]
            self.new_round()

    def qualifier_round(self):
        d = self.data
        pool = d.pop('qualifier_winners', d['qualifiers'])[:]
        if len(pool) == 1:
            d['alive'].append(pool[0])
            self.log(f'{self.name(pool[0])} 패자부활 · 준결승 진출')
            rest = [p for p in d['qualifiers'] if p != pool[0]]
            if rest:
                d['eliminated'].append(rest)
            self.new_round()
            return
        random.SystemRandom().shuffle(pool)
        d['qualifier_winners'] = []
        if len(pool) % 2:
            candidates = [p for p in pool if p not in d['byes']] or pool
            bye = random.SystemRandom().choice(candidates)
            pool.remove(bye)
            d['byes'].append(bye)
            d['qualifier_winners'].append(bye)
            self.log(f'패자부활전 · {self.name(bye)} 부전승')
        d['pending'] = [pool[i:i + 2] for i in range(0, len(pool), 2)]
        self.next_match()

    def roll(self, dice=None):
        d, rng = self.data, random.SystemRandom()
        m = d['current']
        if d['status'] != '진행 중' or m is None:
            raise ValueError('진행 중인 경기가 없습니다.')
        x, y = dice if dice is not None else (rng.randint(1, 6), rng.randint(1, 6))
        m['hp_before'] = m['hp'][:]
        m['dice'], m['turn'] = [x, y], m['turn'] + 1
        if x != y:
            index = 0 if x < y else 1
            m['hp'][index] = max(0, m['hp'][index] - abs(x - y))
        self.log(f"{self.name(m['a'])} {x}:{y} {self.name(m['b'])} · HP {m['hp'][0]}:{m['hp'][1]}")
        if min(m['hp']) > 0:
            return False
        winner, loser = (m['a'], m['b']) if m['hp'][1] == 0 else (m['b'], m['a'])
        d['matches'][m['match_index']]['winner'] = winner
        self.log(f'{self.name(winner)} 승리')
        if d['stage'] == '결승전':
            d['rankings'] = [[winner], [loser]] + d['rankings']
        elif d['stage'] == '3·4위전':
            d['rankings'] = [[winner], [loser]]
        elif d['stage'] == '패자부활전':
            d['qualifier_winners'].append(winner)
        else:
            d['winners'].append(winner)
            d['losers'].append(loser)
        return True

    def plan_match(self, max_turns=32, dice_source=None):
        """Precompute one match without revealing or mutating live results."""
        preview = Tournament.restore(copy.deepcopy(self.data))
        preview.data['current'].pop('animation_plan', None)
        rolls = []
        for _ in range(max_turns):
            done = preview.roll(dice_source() if dice_source else None)
            rolls.append(preview.data['current']['dice'][:])
            if done:
                break
        return dict(rolls=rolls, cursor=0)

    def standings(self):
        return self.data['rankings'] + list(reversed(self.data['eliminated']))
