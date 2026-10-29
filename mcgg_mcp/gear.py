"""Equipment planner for equip_best.

`plan(match)` re-solves the whole equipment layout from zero. Every item (bag and worn, on
board or bench heroes) is free to move, and only heroes deployed on the board can receive
items. Each board hero has three worn-item slots (1, 2 and 3). The crystal slot is a separate
slot (observe() shows it as 4), and crystals are excluded from the planner.

The assignment is an exact min-cost flow, so the optimum is found for the fit model, not
approximated. Current positions only break exact ties, so an item stays where it is when
moving it gains nothing.

Fit model (knowledge.py): an item family is valued by hero role (for example physical
items to marksmen), and scaled by damage type (a physical item on a magic hero is worth
little). Inspire adds attack-speed value for physical carriers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import knowledge as K
from layout import roster_from_match

ITEM_SLOTS = (1, 2, 3)  # worn-item slots; observed live (items sit in 1-3, crystals in 4)
MAX_ITEMS = len(ITEM_SLOTS)
SCALE = 1000          # fit is scaled to integers for the flow solver
TIE_BREAK = 1         # between equal fits, keep an item on the hero it is already on
BAG = None


@dataclass
class Item:
    guid: int
    name: str
    owner: int          # hero guid, or 0 for the bag
    slot: int
    family: str


@dataclass
class GearPlan:
    assign: dict = field(default_factory=dict)   # item guid -> hero guid, or None (bag)
    steps: list = field(default_factory=list)    # ('unequip', item, from_hero) | ('equip', item, hero, slot)
    total_fit: float = 0.0


def fit(item: Item, hero) -> float:
    role, _, dmg = K.hero_info(hero.name)
    if item.family in ('phys', 'magic'):
        if dmg == item.family:
            scale = 1.0
        elif dmg == 'hybrid':
            scale = 0.8
        else:
            scale = 0.35
    else:
        scale = 1.0
    value = K.FAMILY_ROLE_VALUE.get(item.family, {}).get(role, 0.0) * scale
    if item.name == 'Inspire' and role in ('marksman', 'assassin', 'bruiser'):
        value += 0.8
    return value


def _cost(item: Item, hero_guid: int, fit_value: float) -> int:
    """Integer cost of putting `item` on `hero_guid` (lower is better). The fit is optimised
    from scratch; the tie-break only decides between equal fits."""
    c = -round(fit_value * SCALE)
    if item.owner == hero_guid:
        c -= TIE_BREAK
    return c


def _min_cost_flow(n_items, n_heroes, edges, source, sink, n_nodes):
    """Successive shortest paths with Bellman-Ford. edges: [u, v, cap, cost]."""
    graph = [[] for _ in range(n_nodes)]
    for u, v, cap, cost in edges:
        graph[u].append([v, cap, cost, len(graph[v])])
        graph[v].append([u, 0, -cost, len(graph[u]) - 1])
    flow = 0
    while flow < n_items:
        dist = [float('inf')] * n_nodes
        prev = [None] * n_nodes
        dist[source] = 0
        for _ in range(n_nodes):
            changed = False
            for u in range(n_nodes):
                if dist[u] == float('inf'):
                    continue
                for i, (v, cap, cost, _) in enumerate(graph[u]):
                    if cap > 0 and dist[u] + cost < dist[v]:
                        dist[v] = dist[u] + cost
                        prev[v] = (u, i)
                        changed = True
            if not changed:
                break
        if dist[sink] == float('inf'):
            break
        v = sink
        while v != source:
            u, i = prev[v]
            graph[u][i][1] -= 1
            rev = graph[u][i][3]
            graph[v][rev][1] += 1
            v = u
        flow += 1
    return graph


def items_from_match(m) -> list:
    out = []
    for x in m.items:
        fam = K.item_family(x.name)
        if fam is None:
            continue
        out.append(Item(guid=x.guid, name=x.name, owner=x.owner or 0, slot=x.slot, family=fam))
    return out


def candidate_heroes(m) -> list:
    """Heroes that may receive items: only heroes deployed on the board. Bench heroes never
    receive items, but their worn items can be taken and reassigned."""
    return [h for h in roster_from_match(m) if h.on_board]


def plan(m) -> GearPlan:
    heroes = candidate_heroes(m)
    items = items_from_match(m)
    if not heroes or not items:
        return GearPlan(assign={it.guid: (it.owner or BAG) for it in items})

    n, k = len(items), len(heroes)
    # node ids: 0 source, 1..n items, n+1..n+k heroes, n+k+1 bag, n+k+2 sink
    src, bag = 0, n + k + 1
    sink, nodes = n + k + 2, n + k + 3
    edges = []
    fits = {}
    for i, it in enumerate(items, start=1):
        edges.append([src, i, 1, 0])
        edges.append([i, bag, 1, 0])
        for j, h in enumerate(heroes, start=n + 1):
            f = fit(it, h)
            fits[(it.guid, h.guid)] = f
            if f > 0:
                edges.append([i, j, 1, _cost(it, h.guid, f)])
    for j in range(n + 1, n + k + 1):
        edges.append([j, sink, MAX_ITEMS, 0])
    edges.append([bag, sink, n, 0])

    graph = _min_cost_flow(n, k, edges, src, sink, nodes)

    assign, total = {}, 0.0
    for i, it in enumerate(items, start=1):
        target = BAG
        for v, cap, cost, _ in graph[i]:
            if n + 1 <= v <= n + k and cap == 0:
                target = heroes[v - n - 1].guid
        assign[it.guid] = target
        if target is not None:
            total += fits[(it.guid, target)]

    steps = _steps(items, heroes, assign)
    return GearPlan(assign=assign, steps=steps, total_fit=total)


def _steps(items, heroes, assign) -> list:
    """Unequips first (they free slots), then equips in the free slots."""
    by_hero = {h.guid: h for h in heroes}
    kept = {h.guid: set() for h in heroes}
    for it in items:
        if it.owner and assign.get(it.guid) == it.owner and it.slot in ITEM_SLOTS:
            kept[it.owner].add(it.slot)

    steps = []
    for it in items:
        if it.owner and assign.get(it.guid) != it.owner:
            steps.append(('unequip', it.guid, it.owner))

    free = {g: [s for s in ITEM_SLOTS if s not in kept[g]] for g in kept}
    for it in items:
        target = assign.get(it.guid)
        if target is None or target == it.owner:
            continue
        if target not in by_hero:
            continue
        slot = free[target].pop(0) if free[target] else None
        if slot is None:
            raise RuntimeError(f'no free item slot on {by_hero[target].name}')
        steps.append(('equip', it.guid, target, slot))
    return steps
