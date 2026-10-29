"""Offline tests for the layout and gear planners.

No game is needed: matches are built from state.py dataclasses and each plan is replayed
against an in-memory model that enforces the game's rules (empty destination, board
capacity, bench size). Run with:  python -m unittest discover -s tests
"""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'mcgg_mcp'))

import gear  # noqa: E402
import knowledge as K  # noqa: E402
import layout  # noqa: E402
import state as S  # noqa: E402


def make_match(board=(), bench=(), items=(), pop_max=8):
    """board: (guid, name, x, y, star). bench: (guid, name, star). items: (guid, name, owner)."""
    m = S.Match(ok=True, in_match=True, pop_max=pop_max)
    for guid, name, x, y, star in board:
        m.board.append(S.Unit(guid=guid, name=name, star=star, x=x, y=y))
    for slot, (guid, name, star) in enumerate(bench, start=1):
        m.bench.append(S.BenchSlot(slot=slot, guid=guid, name=name, star=star,
                                   quality=K.HERO_COST.get(name, 1)))
    for slot, (guid, name, owner) in enumerate(items, start=1):
        m.items.append(S.Item(guid=guid, name=name, owner=owner, slot=slot if owner else 1))
    return m


def replay_layout(m, steps, cap):
    """Apply layout steps to a model of the board, asserting every game rule on the way."""
    board = {u.guid: (u.x, u.y) for u in m.board if u.name}
    bench = {b.guid: b.slot for b in m.bench if b.name}
    for kind, guid, cell in steps:
        if kind == 'to_bench':
            assert guid in board, f'{guid} is not on the board'
            used = set(bench.values())
            slot = next(s for s in range(1, 10) if s not in used)  # bench must have room
            del board[guid]
            bench[guid] = slot
        elif kind == 'move':
            assert guid in board, f'{guid} is not on the board'
            assert cell not in board.values(), f'move into occupied cell {cell}'
            board[guid] = cell
        elif kind == 'deploy':
            assert guid in bench, f'{guid} is not on the bench'
            assert cell not in board.values(), f'deploy into occupied cell {cell}'
            assert len(board) < cap, 'deploy past board capacity'
            del bench[guid]
            board[guid] = cell
        else:
            raise AssertionError(f'unknown step {kind}')
        assert all(y in layout.ROWS for _, y in board.values()), 'cell outside prep rows'
    return board, bench


class LayoutTests(unittest.TestCase):
    def test_fields_tank_front_and_carry_back(self):
        m = make_match(bench=[(1, 'Miya', 1), (2, 'Tigreal', 1), (3, 'Layla', 1)], pop_max=2)
        p = layout.plan(m)
        self.assertEqual(len(p.target), 2)
        fielded = {g: c for g, c in p.target.items()}
        names = {g: n for g, n in [(1, 'Miya'), (2, 'Tigreal'), (3, 'Layla')]}
        tank = [g for g in fielded if names[g] == 'Tigreal']
        carry = [g for g in fielded if names[g] in ('Miya', 'Layla')]
        self.assertTrue(tank, 'tank must be fielded with a damage carrier')
        self.assertTrue(carry, 'a damage carrier must be fielded')
        self.assertEqual(fielded[tank[0]][1], 2, 'tank belongs in the front row')
        self.assertEqual(fielded[carry[0]][1], 0, 'ranged carry belongs in the back row')

    def test_respects_capacity_and_bench_limit(self):
        names = list(K.HERO_INFO)[:12]
        m = make_match(bench=[(i + 1, n, 1) for i, n in enumerate(names[:9])],
                       board=[(100 + i, n, i % 7, 0, 1) for i, n in enumerate(names[9:12])],
                       pop_max=3)
        p = layout.plan(m)
        self.assertEqual(len(p.target), 3, 'board capacity is 3')
        self.assertEqual(len(p.benched), 9, 'the other nine heroes stay on the bench')

    def test_impossible_roster_is_refused(self):
        names = list(K.HERO_INFO)[:14]
        m = make_match(bench=[(i + 1, n, 1) for i, n in enumerate(names[:9])],
                       board=[(100 + i, n, i % 7, 0, 1) for i, n in enumerate(names[9:14])],
                       pop_max=3)
        with self.assertRaises(ValueError):
            layout.plan(m)

    def test_full_bench_and_full_board_only_permutes_the_board(self):
        names = list(K.HERO_INFO)[:12]
        m = make_match(bench=[(i + 1, n, 1) for i, n in enumerate(names[:9])],
                       board=[(100 + i, n, i, 2, 1) for i, n in enumerate(names[9:12])],
                       pop_max=3)
        p = layout.plan(m)
        self.assertEqual(set(p.target), {100, 101, 102}, 'the fielded set must not change')
        replay_layout(m, p.steps, 3)  # every step legal under the game's rules

    def test_steps_replay_to_the_target_under_game_rules(self):
        rng = random.Random(42)
        names = list(K.HERO_INFO)
        for trial in range(25):
            cap = rng.randint(2, 8)
            cells = [(x, y) for y in layout.ROWS for x in layout.COLS]
            rng.shuffle(cells)
            n_board = rng.randint(0, cap)
            n_bench = rng.randint(0, 9)
            picks = rng.sample(names, n_board + n_bench)
            board = [(200 + i, picks[i], cells[i][0], cells[i][1], rng.choice([1, 1, 2]))
                     for i in range(n_board)]
            bench = [(300 + i, picks[n_board + i], rng.choice([1, 1, 2]))
                     for i in range(n_bench)]
            m = make_match(board=board, bench=bench, pop_max=cap)
            p = layout.plan(m)
            board_end, bench_end = replay_layout(m, p.steps, cap)
            self.assertEqual(board_end, p.target, f'trial {trial}: board did not reach target')
            self.assertLessEqual(len(board_end), cap, f'trial {trial}: over capacity')
            self.assertLessEqual(len(bench_end), 9, f'trial {trial}: bench overflow')

    def test_applied_plan_is_settled(self):
        m = make_match(bench=[(1, 'Miya', 1), (2, 'Tigreal', 1), (3, 'Layla', 1), (4, 'Clint', 1)],
                       pop_max=3)
        first = layout.plan(m)
        board, _ = replay_layout(m, first.steps, 3)
        # Rebuild the match from the layout the plan produced, then plan again.
        names = {1: 'Miya', 2: 'Tigreal', 3: 'Layla', 4: 'Clint'}
        settled = make_match(board=[(g, names[g], x, y, 1) for g, (x, y) in board.items()],
                             pop_max=3)
        bench_left = [(g, names[g], 1) for g in names if g not in board]
        settled.bench.extend(S.BenchSlot(slot=i + 1, guid=g, name=n, star=s, quality=K.HERO_COST[n])
                             for i, (g, n, s) in enumerate(bench_left))
        second = layout.plan(settled)
        self.assertEqual(second.steps, [], 'a settled layout should not churn')

    def test_off_grid_board_entry_is_not_double_counted(self):
        # A hero in transit to the bench is listed on the board at (1000, 1000) and on the bench.
        m = make_match(board=[(5, 'Phoveus', 1000, 1000, 1), (6, 'Miya', 3, 0, 1)],
                       bench=[(5, 'Phoveus', 1)], pop_max=3)
        heroes = layout.roster_from_match(m)
        phoveus = [h for h in heroes if h.guid == 5]
        self.assertEqual(len(phoveus), 1, 'counted once')
        self.assertFalse(phoveus[0].on_board)

    def test_empty_roster_is_a_no_op(self):
        p = layout.plan(make_match(pop_max=3))
        self.assertEqual(p.steps, [])
        self.assertEqual(p.target, {})


class GearTests(unittest.TestCase):
    def assignments_after(self, m, plan):
        owner = {x.guid: x.owner for x in m.items}
        for step in plan.steps:
            if step[0] == 'unequip':
                owner[step[1]] = 0
            else:
                owner[step[1]] = step[2]
        return owner

    def test_items_go_to_the_right_family(self):
        m = make_match(board=[(1, 'Miya', 3, 0, 1), (2, 'Eudora', 2, 0, 1), (3, 'Tigreal', 3, 2, 1)],
                       items=[(10, "Haas' Claws", 0), (11, 'Holy Crystal', 0), (12, 'Guardian Helmet', 0)],
                       pop_max=3)
        p = gear.plan(m)
        self.assertEqual(p.assign[10], 1, 'physical item to the marksman')
        self.assertEqual(p.assign[11], 2, 'magic item to the mage')
        self.assertEqual(p.assign[12], 3, 'defence item to the tank')

    def test_crystals_are_never_moved(self):
        m = make_match(board=[(1, 'Miya', 3, 0, 1)],
                       items=[(10, 'Marksman Magic Crystal', 0), (11, "Haas' Claws", 0)], pop_max=2)
        p = gear.plan(m)
        self.assertNotIn(10, p.assign)
        self.assertEqual(p.assign[11], 1)
        for step in p.steps:
            self.assertNotEqual(step[1], 10)

    def test_worn_item_moves_to_the_better_hero(self):
        m = make_match(board=[(1, 'Tigreal', 3, 2, 1), (2, 'Miya', 3, 0, 1)],
                       items=[(10, "Haas' Claws", 1)], pop_max=2)
        p = gear.plan(m)
        self.assertEqual(p.assign[10], 2, 'a physical item should move to the marksman')
        kinds = [s[0] for s in p.steps]
        self.assertEqual(kinds, ['unequip', 'equip'], 'unequip must precede the equip')
        self.assertEqual(p.steps[1][3] in gear.ITEM_SLOTS, True)

    def test_three_item_cap_per_hero(self):
        m = make_match(board=[(1, 'Miya', 3, 0, 1)],
                       items=[(10 + i, "Haas' Claws" if i % 2 else 'War Axe', 0) for i in range(5)],
                       pop_max=2)
        p = gear.plan(m)
        on_miya = [g for g, h in p.assign.items() if h == 1]
        self.assertLessEqual(len(on_miya), 3)

    def test_slots_are_unique_and_in_range(self):
        rng = random.Random(3)
        names = ['Miya', 'Tigreal', 'Eudora', 'Layla']
        family_names = ["Haas' Claws", 'War Axe', 'Holy Crystal', 'Guardian Helmet',
                        'Winter Crown', 'Blade Armor', 'Ice Queen Wand', 'Golden Staff']
        for trial in range(30):
            board = [(i + 1, names[i], i * 2 % 7, 0, 1) for i in range(rng.randint(1, 4))]
            items = [(100 + i, rng.choice(family_names), rng.choice([0, 0, 1, 2, 3]))
                     for i in range(rng.randint(0, 9))]
            items = [(g, n, o if any(b[0] == o for b in board) else 0) for g, n, o in items]
            m = make_match(board=board, items=items, pop_max=4)
            p = gear.plan(m)
            owner = self.assignments_after(m, p)
            per_hero = {}
            for g, h in owner.items():
                if h:
                    per_hero.setdefault(h, []).append(g)
            for h, lst in per_hero.items():
                self.assertLessEqual(len(lst), 3, f'trial {trial}: hero {h} has more than 3 items')
            for step in p.steps:
                if step[0] == 'equip':
                    self.assertIn(step[3], gear.ITEM_SLOTS, f'trial {trial}: bad slot {step[3]}')
            slots = {}
            for step in p.steps:
                if step[0] == 'equip':
                    key = (step[2], step[3])
                    self.assertNotIn(key, slots, f'trial {trial}: slot used twice')
                    slots[key] = step[1]

    def test_bench_heroes_without_items_never_receive_gear(self):
        m = make_match(board=[(1, 'Tigreal', 3, 2, 1)],
                       bench=[(2, 'Miya', 1)],
                       items=[(10, "Haas' Claws", 0), (11, 'War Axe', 0)], pop_max=2)
        p = gear.plan(m)
        self.assertNotIn(2, {h for h in p.assign.values() if h is not None})
        for step in p.steps:
            if step[0] == 'equip':
                self.assertNotEqual(step[2], 2, 'benched hero with no items must not be equipped')

    def test_bench_hero_gear_is_taken_and_reassigned_to_the_board(self):
        m = make_match(board=[(1, 'Tigreal', 3, 2, 1)],
                       bench=[(2, 'Miya', 1)],
                       items=[(10, "Haas' Claws", 2), (11, 'Guardian Helmet', 0)], pop_max=2)
        p = gear.plan(m)
        self.assertEqual({h.guid for h in gear.candidate_heroes(m)}, {1})
        self.assertEqual(p.assign[10], 1, 'the benched hero gives its item up to the board hero')
        kinds = [s[0] for s in p.steps]
        self.assertEqual(p.steps[0], ('unequip', 10, 2), 'unequip from the bench hero comes first')
        self.assertIn('equip', kinds)

    def test_full_resolve_moves_worn_items_to_the_better_hero(self):
        # Tigreal wears Haas' Claws, but the marksman Miya (also deployed) fits it far better.
        m = make_match(board=[(1, 'Miya', 3, 0, 1), (2, 'Tigreal', 3, 2, 1)],
                       items=[(10, "Haas' Claws", 2), (11, 'Guardian Helmet', 0)], pop_max=3)
        p = gear.plan(m)
        self.assertEqual(p.assign[10], 1)
        self.assertEqual(p.assign[11], 2)
        self.assertEqual(p.steps[0], ('unequip', 10, 2))
        equips = [s for s in p.steps if s[0] == 'equip']
        self.assertEqual({s[1] for s in equips}, {10, 11})

    def test_equal_fit_keeps_the_item_where_it_is(self):
        # Two identical tanks: moving the helmet from Hylos to Tigreal gains nothing.
        m = make_match(board=[(1, 'Tigreal', 3, 2, 1), (2, 'Hylos', 1, 2, 1)],
                       items=[(10, 'Guardian Helmet', 2)], pop_max=2)
        p = gear.plan(m)
        self.assertEqual(p.assign[10], 2)
        self.assertEqual(p.steps, [], 'a tie must not cause a move')

    def test_settled_items_need_no_steps(self):
        m = make_match(board=[(1, 'Miya', 3, 0, 1)], items=[(10, "Haas' Claws", 1)], pop_max=2)
        m.items[0].slot = 2
        p = gear.plan(m)
        self.assertEqual(p.steps, [])


if __name__ == '__main__':
    unittest.main()
