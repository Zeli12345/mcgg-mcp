"""Board layout planner for auto_deploy.

Pure functions, no bridge calls: `plan(match)` returns the target layout and the ordered
move steps that reach it. The guard executes the steps and checks each one.

Model
-----
- Roster: every named hero on the board or the bench.
- Fielded: the heroes that go on the board. The count is capped by board capacity
  (`player.maxPopulation`) and floored so the bench (9 slots) never overflows.
- Usable cells: rows 0-2, the only rows the game accepts during prep (verified live
  by guard.py). Row 2 is the front, row 0 the back.
- Objective: each fielded hero scores value x position factor. Position factors favour
  tanks in front, ranged carries in the back row, and carries near the middle column.
  Team terms reward having a tank and a damage carrier fielded, and reward synergy
  breakpoints. Every hero that changes location costs a small move penalty, so a
  settled layout is not shuffled.
- Search: deterministic hill climbing from a few starts (the current layout and a
  greedy one), using relocate, swap, bring-in, bench-out and replace moves.
- Sequencing: the steps are ordered so every move is legal when issued. Deploys come
  before benchings, so the bench has room. When the bench and the board are both full,
  only swaps within the board are possible, so the search keeps the same fielded set.

The objective is a heuristic. No battle simulator exists here, so "best" means best under
this model, not proven best in combat.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import knowledge as K

ROWS = (0, 1, 2)
COLS = range(7)
CELLS = tuple((x, y) for y in ROWS for x in COLS)
BENCH_SIZE = 9
MOVE_PENALTY = 0.03      # fraction of the mean hero value per location change
RESTARTS = 8
ITERATIONS = 2000
SEED = 7
MAX_STEPS = 2000

CARRY_ROLES = ('marksman', 'mage', 'assassin')

# row factor per (role, range); the x factor is applied on top
ROW_PREF = {
    ('tank', 'melee'): {2: 1.0, 1: 0.7, 0: 0.35},
    ('bruiser', 'melee'): {2: 0.9, 1: 1.0, 0: 0.5},
    ('bruiser', 'ranged'): {2: 0.5, 1: 0.9, 0: 1.0},
    ('assassin', 'melee'): {2: 0.6, 1: 0.9, 0: 1.0},
    ('assassin', 'ranged'): {2: 0.4, 1: 0.8, 0: 1.0},
    ('marksman', 'ranged'): {2: 0.2, 1: 0.7, 0: 1.0},
    ('mage', 'ranged'): {2: 0.2, 1: 0.7, 0: 1.0},
    ('mage', 'melee'): {2: 0.4, 1: 0.8, 0: 1.0},
    ('support', 'ranged'): {2: 0.3, 1: 0.8, 0: 1.0},
    ('support', 'melee'): {2: 0.5, 1: 0.9, 0: 0.8},
}
DEFAULT_ROW_PREF = {2: 0.6, 1: 0.8, 0: 0.9}


@dataclass
class Hero:
    guid: int
    name: str
    star: int
    cost: int
    cell: tuple | None = None       # (x, y) when on the board
    bench_slot: int | None = None   # 1..9 when on the bench

    @property
    def role(self):
        return K.hero_info(self.name)[0]

    @property
    def range(self):
        return K.hero_info(self.name)[1]

    @property
    def on_board(self):
        return self.cell is not None


@dataclass
class Plan:
    target: dict = field(default_factory=dict)   # guid -> (x, y) for fielded heroes
    steps: list = field(default_factory=list)    # ('to_bench'|'move'|'deploy', guid, cell)
    score: float = 0.0
    benched: list = field(default_factory=list)  # guids that end on the bench


def hero_value(h: Hero) -> float:
    power = K.COST_VALUE.get(h.cost, 1.0) * K.STAR_MULTIPLIER.get(h.star, 1.0)
    return power * K.ROLE_WEIGHT.get(h.role, 0.8)


def position_factor(h: Hero, cell) -> float:
    x, y = cell
    row = ROW_PREF.get((h.role, h.range), DEFAULT_ROW_PREF)[y]
    spread = 0.06 if h.role in CARRY_ROLES else 0.03
    return row * (1 - spread * abs(x - 3))


def roster_from_match(m) -> list:
    """Named heroes on the board and bench, with cost from the config table."""
    heroes = []
    for u in m.board:
        # A hero in transit to the bench is still listed on the board at (1000, 1000); it is
        # counted once, from the bench list, so only in-grid cells count as on the board.
        if u.name and 0 <= u.x < len(COLS) and 0 <= u.y < 6:
            cost = K.HERO_COST.get(u.name, u.quality or 1)
            heroes.append(Hero(u.guid, u.name, u.star or 1, cost, cell=(u.x, u.y)))
    for b in m.bench:
        if b.name:
            cost = K.HERO_COST.get(b.name, b.quality or 1)
            heroes.append(Hero(b.guid, b.name, b.star or 1, cost, bench_slot=b.slot))
    return heroes


def capacity(m, roster) -> int:
    """Board capacity: the game's population cap, else the board count already in use."""
    cap = m.pop_max or 0
    if cap <= 0:
        cap = sum(1 for h in roster if h.on_board)
    return min(cap, len(CELLS))


def _context(heroes):
    """Per-roster data the objective needs, computed once."""
    values = {h.guid: hero_value(h) for h in heroes}
    mean_value = (sum(values.values()) / len(values)) if values else 1.0
    names = {h.name for h in heroes}
    syn = []
    for members in K.SYNERGIES.values():
        present = frozenset(n for n in members if n in names)
        if present:
            syn.append(present)
    return {
        'by_guid': {h.guid: h for h in heroes},
        'values': values,
        'mean': mean_value,
        'syn': syn,
        'roster_tank': any(h.role == 'tank' for h in heroes),
        'roster_carry': any(h.role in CARRY_ROLES for h in heroes),
        'move_cost': MOVE_PENALTY * mean_value,
        'heroes': heroes,
    }


def _objective(ctx, layout) -> float:
    """layout: guid -> cell for fielded heroes. Higher is better."""
    if not layout:
        return float('-inf')
    by_guid, values, mean = ctx['by_guid'], ctx['values'], ctx['mean']
    total = 0.0
    fielded_roles = set()
    fielded_names = set()
    for g, cell in layout.items():
        h = by_guid[g]
        total += values[g] * position_factor(h, cell)
        fielded_roles.add(h.role)
        fielded_names.add(h.name)
    if ctx['roster_tank'] and 'tank' not in fielded_roles:
        total -= 1.5 * mean
    if ctx['roster_carry'] and not (fielded_roles & set(CARRY_ROLES)):
        total -= 1.0 * mean
    for members in ctx['syn']:
        count = len(members & fielded_names)
        bonus = 0.0
        for need, weight in K.SYNERGY_BREAKPOINTS:
            if count >= need:
                bonus = weight
        total += bonus * mean
    move_cost = ctx['move_cost']
    for h in ctx['heroes']:
        if h.guid in layout:
            if layout[h.guid] != h.cell:
                total -= move_cost
        elif h.on_board:
            total -= move_cost  # being benched is a move too
    return total


def _search(heroes, cap, rng, start_layout, ctx, min_fielded, fixed):
    """Hill climbing on the layout. Returns (layout, score).

    fixed=True keeps the fielded set as it is and only moves heroes within the board."""
    guids = [h.guid for h in heroes]
    layout = dict(start_layout)
    best = _objective(ctx, layout)

    def free_cells(lay):
        taken = set(lay.values())
        return [c for c in CELLS if c not in taken]

    for _ in range(ITERATIONS):
        cand = dict(layout)
        fielded = list(cand)
        idle = [g for g in guids if g not in cand]
        pick = rng.random()
        if pick < 0.4 and fielded:                       # relocate one fielded hero
            g = rng.choice(fielded)
            free = free_cells(cand)
            if free:
                cand[g] = rng.choice(free)
        elif pick < 0.7 and len(fielded) >= 2:           # swap two fielded heroes
            a, b = rng.sample(fielded, 2)
            cand[a], cand[b] = cand[b], cand[a]
        elif fixed:
            continue
        elif pick < 0.82 and idle and len(fielded) < cap:  # bring one idle hero in
            g = rng.choice(idle)
            free = free_cells(cand)
            if free:
                cand[g] = rng.choice(free)
        elif pick < 0.92 and fielded and len(fielded) > min_fielded:  # bench one hero
            del cand[rng.choice(fielded)]
        elif fielded and idle:                           # replace a fielded hero
            out = rng.choice(fielded)
            inn = rng.choice(idle)
            cand[inn] = cand.pop(out)
        if not cand or len(cand) > cap or len(cand) < min_fielded:
            continue
        score = _objective(ctx, cand)
        if score > best + 1e-9:
            best, layout = score, cand
    return layout, best


def _best_layout(heroes, cap, min_fielded):
    ctx = _context(heroes)
    values = ctx['values']
    rng = random.Random(SEED)

    current = {h.guid: h.cell for h in heroes if h.on_board and h.cell in CELLS}
    board_count = sum(1 for h in heroes if h.on_board)
    bench_count = len(heroes) - board_count
    # Bench full and board at capacity: no hero can change group, only cells can change.
    locked = bench_count >= BENCH_SIZE and board_count >= cap
    if locked:
        best_layout, best_score = None, float('-inf')
        for _ in range(RESTARTS):
            lay, score = _search(heroes, cap, rng, current, ctx, min_fielded, fixed=True)
            if score > best_score:
                best_layout, best_score = lay, score
        return best_layout or current, best_score

    if len(current) > cap:
        keep = sorted(current, key=lambda g: -values[g])[:cap]
        current = {g: current[g] for g in keep}
    starts = [current]
    greedy, free = {}, list(CELLS)
    for h in sorted(heroes, key=lambda h: -values[h.guid])[:cap]:
        cell = max(free, key=lambda c: position_factor(h, c))
        free.remove(cell)
        greedy[h.guid] = cell
    starts.append(greedy)
    best_layout, best_score = None, float('-inf')
    for i in range(RESTARTS):
        start = starts[i % len(starts)]
        lay, score = _search(heroes, cap, rng, start, ctx, min_fielded, fixed=False)
        if score > best_score:
            best_layout, best_score = lay, score
    filled = _fill(heroes, best_layout or {}, cap, ctx)
    return filled, _objective(ctx, filled)


def _fill(heroes, layout, cap, ctx):
    """Field idle heroes while board slots are free. A benched hero adds nothing in combat,
    so an empty slot is never the better choice; each hero goes to its best free cell."""
    layout = dict(layout)
    while len(layout) < min(cap, len(heroes)):
        taken = set(layout.values())
        free = [c for c in CELLS if c not in taken]
        idle = [h for h in heroes if h.guid not in layout]
        if not free or not idle:
            break
        gain, guid, cell = max(
            ((ctx['values'][h.guid] * position_factor(h, c), h.guid, c)
             for h in idle for c in free),
            key=lambda t: t[0])
        layout[guid] = cell
    return layout


def sequence(heroes, target, cap) -> list:
    """Ordered steps from the current layout to `target` (guid -> cell; benched guids absent).

    Priority at each step, so every move is legal when it is issued:
      1. move a board hero into its empty target cell
      2. deploy a bench hero into its empty target cell, if the board has room
      3. bench an unfielded board hero, if the bench has room
      4. break a blocked cycle: move a blocked hero to a free cell outside the targets
      5. break it by benching the blocked hero, if the bench has room
    """
    pos_cell = {h.guid: h.cell for h in heroes if h.on_board}
    pos_bench = {h.guid: h.bench_slot for h in heroes if not h.on_board}
    steps = []
    targets = set(target.values())

    def done():
        if any(pos_cell.get(g) != cell for g, cell in target.items()):
            return False
        if any(g in pos_bench for g in target):
            return False
        return all(g in target for g in pos_cell)

    for _ in range(MAX_STEPS):
        if done():
            return steps
        occupied = set(pos_cell.values())
        board_count = len(pos_cell)

        step = None
        for g, cell in target.items():                       # 1
            if g in pos_cell and pos_cell[g] != cell and cell not in occupied:
                step = ('move', g, cell)
                break
        if step is None:
            for g, cell in target.items():                   # 2
                if g in pos_bench and cell not in occupied and board_count < cap:
                    step = ('deploy', g, cell)
                    break
        if step is None:
            for g in list(pos_cell):                         # 3
                if g not in target and len(pos_bench) < BENCH_SIZE:
                    step = ('to_bench', g, None)
                    break
        if step is not None:
            kind, g, cell = step
            if kind == 'move':
                pos_cell[g] = cell
            elif kind == 'deploy':
                pos_cell[g] = cell
                del pos_bench[g]
            else:
                del pos_cell[g]
                pos_bench[g] = 'any'
            steps.append(step)
            continue

        blocked = [g for g in target if g in pos_cell and pos_cell[g] != target[g]]
        if not blocked:
            raise RuntimeError('layout sequencing stalled: a benched hero has no target')
        g = blocked[0]
        temp = next((c for c in CELLS if c not in occupied and c not in targets), None)
        if temp is not None:                                 # 4
            steps.append(('move', g, temp))
            pos_cell[g] = temp
        elif len(pos_bench) < BENCH_SIZE:                    # 5
            steps.append(('to_bench', g, None))
            del pos_cell[g]
            pos_bench[g] = 'any'
        else:
            raise RuntimeError('no legal order from this layout: bench and board are both full')
    raise RuntimeError('layout sequencing did not converge')


def plan(m, cap=None) -> Plan:
    """cap: the board's slot capacity from the game (guard reads m_iSlotPopulation). Falls
    back to the state's own count when the caller cannot read it."""
    heroes = roster_from_match(m)
    if not heroes:
        return Plan()
    cap = capacity(m, heroes) if cap is None else min(cap, len(CELLS))
    min_fielded = max(0, len(heroes) - BENCH_SIZE)
    if cap < min_fielded:
        raise ValueError(f'{len(heroes)} heroes do not fit: board capacity {cap}, bench 9')
    target, score = _best_layout(heroes, cap, min_fielded)
    steps = sequence(heroes, target, cap)
    return Plan(target=target, steps=steps, score=score,
                benched=[h.guid for h in heroes if h.guid not in target])
