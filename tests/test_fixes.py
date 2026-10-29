"""Regression tests for the live-match fixes (no game needed).

Covers: the observe text KeyError, enemy units in the fight board, the fight-phase revision,
legal actions outside shopping, equip verification and slot choice, the crystal bond guard,
and the level-up readback. Run with:  python -m unittest discover -s tests
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'mcgg_mcp'))

import gear  # noqa: E402
import guard  # noqa: E402
import observe  # noqa: E402
import state as S  # noqa: E402

ME = 111
PREP = 'GamePhasePrepare'
FIGHT = 'GamePhaseFight'


def make_match(phase=PREP, coin=30, level=7, level_price=20, board=(), items=(), shop=()):
    m = S.Match(ok=True, in_match=True, account=ME, phase=phase, round_no=5, coin=coin,
                level=level, level_price=level_price, hp=100, hp_max=100)
    for guid, name, x, y, star in board:
        m.board.append(S.Unit(guid=guid, name=name, star=star, x=x, y=y, account=ME))
    for guid, name, owner, slot in items:
        m.items.append(S.Item(guid=guid, name=name, owner=owner, slot=slot))
    for slot, (hero_id, name, cost) in enumerate(shop):
        m.shop.append(S.ShopSlot(slot=slot, hero_id=hero_id, name=name, cost=cost))
    return m


class FakeObserver:
    """Returns the queued matches in order; the last one repeats."""

    def __init__(self, *states):
        self.states = list(states)

    def load(self):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def gogo_state(self):
        return {'active': False}

    def crystal_state(self):
        return {'active': False}

    def welfare_state(self, raw=None):
        return {'active': False}

    def auction_phase(self):
        return None

    ITEM_NAMES = {4001: 'Inspire', 10001: 'Choice Magic Crystal'}

    def item_name(self, item_id):
        return self.ITEM_NAMES.get(item_id)


class FakeBridge:
    def __init__(self, equip_result=None, act_result=None):
        self.equip_result = equip_result or {'ok': True, 'result': 'True', 'newSlot': 1}
        self.act_result = act_result or {'ok': True}
        self.calls = []

    def equip(self, item, hero, slot=1):
        self.calls.append(('equip', item, hero, slot))
        return self.equip_result

    def act(self, **kw):
        self.calls.append(('act', kw))
        return self.act_result


def engine(bridge, *states):
    e = guard.Engine.__new__(guard.Engine)  # skip __init__: only the bridge and observer are used
    e.b = bridge
    e.o = FakeObserver(*states)
    e.dry_run = False
    e.stamps = []
    e.max_per_minute = 1000
    return e


NO_SLEEP = mock.patch('guard.time.sleep', lambda *_: None)


class ObserveTextTests(unittest.TestCase):
    def test_text_render_survives_shop_slots_without_quality(self):
        # the live KeyError: shop entries never carry 'quality', and the text line read it
        o = {'round': {'n': 4, 'label': 'I-4', 'phase': 'GamePhasePrepare'},
             'timers': {'left_ms': 9000}, 'me': {'coin': 30, 'level': 5, 'level_price': 8, 'hp': 100,
                                                 'hp_max': 100, 'power': 0, 'interest': 3},
             'shop': {'refresh_cost': 2, 'bench_free': 9,
                      'slots': [{'slot': 0, 'name': 'Miya', 'cost': 2, 'owned': 1, 'makes': 'pair'}]},
             'pending': {'none': True}}
        text = observe.render_text(o, make_match())
        self.assertIn('Miya', text)
        self.assertIn('-> pair', text)


class EnemyUnitsTests(unittest.TestCase):
    def payload(self, units):
        return {'ok': True, 'inMatch': True,
                'player': {'data': {'accId': ME}, 'coin': 10, 'level': 5, 'hp': 80, 'maxHp': 100},
                'round': {'number': 5, 'phase': FIGHT},
                'board': {'units': units}}

    def test_fight_board_keeps_only_this_accounts_units(self):
        units = [{'guid': 1, 'name': 'Hylos', 'accountId': ME, 'gridX': 3, 'gridY': 2},
                 {'guid': 2, 'name': 'Miya', 'accountId': 222, 'gridX': 3, 'gridY': 4}]
        m = S.parse(self.payload(units))
        self.assertEqual([u.name for u in m.board], ['Hylos'])

    def test_unit_without_owner_is_kept(self):
        units = [{'guid': 1, 'name': 'Hylos', 'gridX': 3, 'gridY': 2}]
        m = S.parse(self.payload(units))
        self.assertEqual([u.name for u in m.board], ['Hylos'])


class RevisionTests(unittest.TestCase):
    def test_fight_revision_ignores_moving_units_and_gold(self):
        a = make_match(phase=FIGHT, coin=30, board=[(1, 'Hylos', 3, 2, 1)])
        b = make_match(phase=FIGHT, coin=31, board=[(1, 'Hylos', 4, 5, 1)])
        self.assertEqual(a.rev(), b.rev())

    def test_prep_revision_still_tracks_gold(self):
        a = make_match(phase=PREP, coin=30)
        b = make_match(phase=PREP, coin=31)
        self.assertNotEqual(a.rev(), b.rev())


class LegalActionTests(unittest.TestCase):
    def test_purchases_are_not_legal_during_a_fight(self):
        shop = [(1, 'Miya', 2)]
        m = make_match(phase=FIGHT, coin=50, level_price=10, shop=shop,
                       board=[(1, 'Hylos', 3, 2, 1)], items=[(50, 'War Axe', 0, 1)])
        legal = observe.legal_actions(m)
        for tool in ('buy_hero', 'reroll_shop', 'buy_xp', 'lock_shop', 'equip', 'equip_best'):
            self.assertNotIn(tool, legal)
        self.assertIn('observe', legal)

    def test_purchases_are_legal_in_prep(self):
        shop = [(1, 'Miya', 2)]
        m = make_match(phase=PREP, coin=50, level_price=10, shop=shop,
                       board=[(1, 'Hylos', 3, 2, 1)])
        legal = observe.legal_actions(m)
        for tool in ('buy_hero', 'reroll_shop', 'buy_xp'):
            self.assertIn(tool, legal)


class EquipTests(unittest.TestCase):
    def setUp(self):
        self.hero = 10
        self.board = [(self.hero, 'Irithel', 6, 0, 1)]

    def test_game_refusal_is_no_effect(self):
        m = make_match(board=self.board, items=[(50, "Haas' Claws", 0, 1)])
        b = FakeBridge(equip_result={'ok': True, 'result': 'False', 'newSlot': -1})
        with NO_SLEEP:
            res, verified = engine(b, m)._equip(50, self.hero, None, m)
        self.assertIs(verified, False)

    def test_accepted_call_that_never_lands_is_no_effect(self):
        # the live failure: the bridge said True and newSlot was set, but the item stayed in the bag
        m = make_match(board=self.board, items=[(50, "Haas' Claws", 0, 1)])
        b = FakeBridge(equip_result={'ok': True, 'result': 'True', 'newSlot': 2})
        with NO_SLEEP:
            res, verified = engine(b, m, m)._equip(50, self.hero, None, m)
        self.assertIs(verified, False)

    def test_landed_item_is_verified(self):
        before = make_match(board=self.board, items=[(50, "Haas' Claws", 0, 1)])
        after = make_match(board=self.board, items=[(50, "Haas' Claws", self.hero, 2)])
        b = FakeBridge(equip_result={'ok': True, 'result': 'True', 'newSlot': 2})
        with NO_SLEEP:
            res, verified = engine(b, before, after)._equip(50, self.hero, 2, before)
        self.assertIs(verified, True)

    def test_occupied_slot_is_refused_before_sending(self):
        m = make_match(board=self.board,
                       items=[(60, "Berserker's Fury", self.hero, 2), (50, "Haas' Claws", 0, 1)])
        b = FakeBridge()
        with self.assertRaisesRegex(ValueError, 'already holds'):
            engine(b, m)._equip(50, self.hero, 2, m)
        self.assertEqual(b.calls, [])

    def test_auto_slot_takes_the_first_free_worn_slot(self):
        m = make_match(board=self.board,
                       items=[(60, 'War Axe', self.hero, 1), (61, "Berserker's Fury", self.hero, 2),
                              (50, "Haas' Claws", 0, 1)])
        b = FakeBridge()
        with NO_SLEEP:
            engine(b, m, m)._equip(50, self.hero, None, m)
        self.assertEqual(b.calls[-1], ('equip', 50, self.hero, 3))

    def test_full_hero_is_refused(self):
        m = make_match(board=self.board,
                       items=[(60, 'War Axe', self.hero, 1), (61, 'Inspire', self.hero, 2),
                              (62, 'Blade Armor', self.hero, 3), (50, "Haas' Claws", 0, 1)])
        with self.assertRaisesRegex(ValueError, 'three items'):
            engine(FakeBridge(), m)._equip(50, self.hero, None, m)

    def test_slot_four_is_not_a_worn_slot(self):
        m = make_match(board=self.board, items=[(50, 'War Axe', 0, 1)])
        with self.assertRaisesRegex(ValueError, 'crystal slot'):
            engine(FakeBridge(), m)._equip(50, self.hero, 4, m)

    def test_bench_hero_is_refused(self):
        m = make_match(board=[], items=[(50, 'War Axe', 0, 1)])
        with self.assertRaisesRegex(ValueError, 'board'):
            engine(FakeBridge(), m)._equip(50, self.hero, None, m)

    def test_second_crystal_on_a_hero_is_refused(self):
        m = make_match(board=self.board,
                       items=[(70, 'Marksman Magic Crystal', self.hero, 4), (71, 'Choice Magic Crystal', 0, 1)])
        with self.assertRaisesRegex(ValueError, 'already has a crystal'):
            engine(FakeBridge(), m)._equip(71, self.hero, None, m)

    def test_nameless_owned_items_are_named_by_id(self):
        # live: an owned crystal and worn item arrived with name=None; the crystal check and the
        # slot check must still see them by id, or the crystal went down the worn-item path
        m = make_match(board=self.board, items=[(60, None, self.hero, 1), (71, None, 0, 1)])
        m.items[0].item_id = 4001
        m.items[1].item_id = 10001
        after = make_match(board=self.board, items=[(72, None, self.hero, 4)])
        after.items[0].item_id = 10001
        b = FakeBridge()
        with NO_SLEEP:
            engine(b, m, after)._equip(71, self.hero, None, m)
        self.assertEqual(b.calls[-1], ('equip', 71, self.hero, 1))

    def test_crystal_goes_to_the_crystal_slot(self):
        m = make_match(board=self.board, items=[(71, 'Choice Magic Crystal', 0, 1)])
        b = FakeBridge()
        after = make_match(board=self.board, items=[(72, 'Choice Magic Crystal', self.hero, 4)])
        with NO_SLEEP:
            res, verified = engine(b, m, after)._equip(71, self.hero, None, m)
        self.assertEqual(b.calls[-1], ('equip', 71, self.hero, 1))
        self.assertIs(verified, True)


class UnequipCrystalTests(unittest.TestCase):
    def test_crystal_removal_needs_confirmation(self):
        m = make_match(board=[(10, 'Tigreal', 4, 2, 2)], items=[(35, 'Choice Magic Crystal', 10, 4)])
        e = engine(FakeBridge(), m)
        with self.assertRaisesRegex(ValueError, 'confirm_bond_loss'):
            e._execute('unequip', {'item_guid': 35}, m)

    def test_crystal_removal_with_confirmation_proceeds(self):
        m = make_match(board=[(10, 'Tigreal', 4, 2, 2)], items=[(35, 'Choice Magic Crystal', 10, 4)])
        bagged = make_match(board=[(10, 'Tigreal', 4, 2, 2)], items=[(35, 'Choice Magic Crystal', 0, 1)])
        b = FakeBridge()
        with NO_SLEEP:
            res, verified = engine(b, m, bagged)._execute('unequip',
                                                          {'item_guid': 35, 'confirm_bond_loss': True}, m)
        self.assertIs(verified, True)


class LevelUpReadbackTests(unittest.TestCase):
    def test_level_up_reports_the_observed_level(self):
        before = make_match(phase=PREP, coin=40, level=6, level_price=20)
        after = make_match(phase=PREP, coin=20, level=7, level_price=32)
        # the bridge's immediate reply still says levelAfter 6; the observed level is 7
        b = FakeBridge(act_result={'ok': True, 'levelBefore': 6, 'levelAfter': 6})
        with NO_SLEEP:
            res, verified = engine(b, before, after)._execute('buy_xp', {}, before)
        self.assertIs(verified, True)
        self.assertEqual(res['levelAfter'], 7)
        self.assertEqual(res['levelBefore'], 6)


class PlannerSlotTests(unittest.TestCase):
    def test_planned_items_use_the_worn_slots(self):
        self.assertEqual(gear.ITEM_SLOTS, (1, 2, 3))


if __name__ == '__main__':
    unittest.main()
