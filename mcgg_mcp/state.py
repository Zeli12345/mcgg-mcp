"""Match state parsing + the observe envelope.

Scope: a typed read-model of the operator's own game client, parsed from the local
bridge payload. No mutation and no external I/O.

Two renderings of one model:
  format="json"  typed envelope, readable keys, nulls omitted   (~700-900 tokens)
  format="text"  aligned prose                                    (~260-320 tokens)
detail="summary" drops per-unit verbosity; "full" adds grids, timers, bonds, damage.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

LBM = 'MCLogicBattleData.battleManager'
AUCTION = LBM + '.m_LogicManager.m_LogicRoundMgr.m_AuctionComp'
ROUND = LBM + '.m_LogicManager.m_LogicRoundMgr'
LOGIC = LBM + '.m_LogicManager'
CRYSTAL = LBM + '.m_MCLogicVersatileCrystalComp'
SUPER = LBM + '.m_SuperCrystal'
GOGO = LBM + '.m_GoGoCardComp'
BOND = LBM + '.m_BondComp'
PICK = LBM + '.m_ChessPick'

SHOPPING = ('GamePhasePrepare', 'GamePhaseForecast', 'GamePhaseWelfare')


def i(v, d: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def oi(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@dataclass
class Unit:
    guid: int = 0
    hero_id: int = 0
    name: Optional[str] = None
    star: int = 0
    quality: Optional[int] = None
    x: int = 0
    y: int = 0
    account: int = 0
    items: list = field(default_factory=list)


@dataclass
class ShopSlot:
    slot: int = 0
    hero_id: int = 0
    name: Optional[str] = None
    cost: int = 0
    sell: int = 0
    quality: Optional[int] = None
    kind: str = 'Hero'


@dataclass
class BenchSlot:
    slot: int = 0
    guid: int = 0
    hero_id: int = 0
    name: Optional[str] = None
    star: int = 0
    quality: Optional[int] = None
    sell: int = 0


@dataclass
class Item:
    guid: int = 0
    item_id: int = 0
    name: Optional[str] = None
    owner: int = 0
    slot: int = 0
    upgrade: int = 0


@dataclass
class Match:
    ok: bool = False
    in_match: bool = False
    account: int = 0
    coin: int = 0
    level: int = 0
    hp: int = 0
    hp_max: int = 0
    population: int = 0
    pop_max: int = 0
    level_price: int = 0
    round_no: int = 0
    phase: str = ''
    stage: int = 0
    invade: bool = False
    welfare: bool = False
    shop: list = field(default_factory=list)
    refresh_cost: int = 0
    locked: bool = False
    bench: list = field(default_factory=list)
    board: list = field(default_factory=list)
    items: list = field(default_factory=list)
    offers: list = field(default_factory=list)
    bonds: list = field(default_factory=list)
    fight: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @property
    def shopping(self) -> bool:
        return self.phase in SHOPPING

    @property
    def seated(self) -> bool:
        return self.in_match and self.account != 0

    def copies(self) -> dict:
        c: dict[str, int] = {}
        for u in self.board:
            if u.name:
                c[u.name] = c.get(u.name, 0) + 1
        for b in self.bench:
            if b.name:
                c[b.name] = c.get(b.name, 0) + 1
        return c

    def free_items(self) -> list:
        return [x for x in self.items if not x.owner]

    def power(self) -> int:
        return sum((u.star or 1) * (u.quality or 1) for u in self.board if u.name)

    def rev(self) -> int:
        # Outside the shopping phases the board, gold, HP and shop move every frame (units
        # walk, income ticks, damage lands), so an expect_rev taken in a fight was stale a
        # moment later. There the revision only tracks what a fight action can depend on:
        # the round, the phase, the prompts and the bonds.
        if not self.shopping:
            sig = {
                'r': self.round_no, 'p': self.phase,
                'o': [x.get('guid') for x in self.offers],
                'd': [(str(x.get('id')), str(x.get('value'))) for x in self.bonds],
            }
            return int(hashlib.md5(json.dumps(sig, sort_keys=True, default=str).encode()).hexdigest()[:8], 16)
        sig = {
            'r': self.round_no, 'p': self.phase, 'c': self.coin, 'l': self.level,
            'hp': self.hp, 's': [(x.slot, x.hero_id, x.cost) for x in self.shop],
            'b': [(x.slot, x.guid, x.name) for x in self.bench],
            'u': [(x.guid, x.hero_id, x.x, x.y, tuple(x.items)) for x in self.board],
            'i': [(x.guid, x.owner, x.slot) for x in self.items],
            'o': [x.get('guid') for x in self.offers],
            'd': [(str(x.get('id')), str(x.get('value'))) for x in self.bonds],
        }
        return int(hashlib.md5(json.dumps(sig, sort_keys=True, default=str).encode()).hexdigest()[:8], 16)


def parse(payload: dict) -> Match:
    m = Match(raw=payload)
    if not payload or not payload.get('ok'):
        m.in_match = bool(payload.get('inMatch'))
        return m
    m.ok = True
    m.in_match = True
    p = payload.get('player') or {}
    d = p.get('data') or {}
    r = payload.get('round') or {}
    s = payload.get('shop') or {}

    m.account = i(d.get('accId'))
    m.coin, m.level = i(p.get('coin')), i(p.get('level'))
    m.hp, m.hp_max = i(p.get('hp')), i(p.get('maxHp'))
    m.population, m.pop_max = i(p.get('population')), i(p.get('maxPopulation'))
    m.level_price = i(p.get('levelPrice'))
    m.round_no, m.phase = i(r.get('number')), str(r.get('phase') or '')
    m.stage = i(r.get('stage'))
    m.invade = str(r.get('invade')).lower() == 'true'
    m.welfare = str(r.get('welfare')).lower() == 'true'
    m.refresh_cost = i(s.get('refreshCost'))
    m.locked = str(s.get('locked')).lower() == 'true'

    for x in s.get('slots') or []:
        m.shop.append(ShopSlot(slot=i(x.get('slot')), hero_id=i(x.get('id')), name=x.get('name'),
                               cost=i(x.get('price')), sell=i(x.get('sellPrice')),
                               quality=oi(x.get('quality')), kind=str(x.get('kind') or 'Hero')))
    for x in (payload.get('bench') or {}).get('slots') or []:
        if not x.get('occupied'):
            continue
        m.bench.append(BenchSlot(slot=i(x.get('slot')), guid=i(x.get('guid')), hero_id=i(x.get('heroId')),
                                 name=x.get('name'), star=i(x.get('star')), quality=oi(x.get('quality')),
                                 sell=i(x.get('sellPrice'))))
    for x in (payload.get('board') or {}).get('units') or []:
        # a unit without a hero name is a non-hero board entity (its guid changes on every
        # read); leave it out so counts and copies only describe real heroes
        if not x.get('name'):
            continue
        # during a fight the bridge's board list also carries the opponents' units (the
        # 19-unit fight board seen live). Keep only units that belong to this account.
        owner = i(x.get('accountId'))
        if m.account and owner and owner != m.account:  # 0 = unknown owner, keep the unit
            continue
        m.board.append(Unit(guid=i(x.get('guid')), hero_id=i(x.get('heroId')), name=x.get('name'),
                            star=i(x.get('star')), quality=oi(x.get('quality')),
                            x=i(x.get('gridX')), y=i(x.get('gridY')), account=i(x.get('accountId')),
                            items=list(x.get('equipped') or [])))
    for x in (payload.get('items') or {}).get('owned') or []:
        m.items.append(Item(guid=i(x.get('guid')), item_id=i(x.get('id')), name=x.get('name'),
                            owner=i(x.get('ownerGuid')), slot=i(x.get('slot')), upgrade=i(x.get('upgrade'))))
    m.offers = list(payload.get('offers') or [])
    m.bonds = list(payload.get('bonds') or [])
    m.fight = payload.get('fight') or {}
    return m