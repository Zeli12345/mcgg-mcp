"""Build the observe payload: JSON envelope or compact text, summary or full.

Scope: read-only view of the operator's own game client, assembled from the local bridge
on 127.0.0.1:8787. Nothing here mutates state or contacts anything off-machine.

Everything here is derived from one /match call plus a few cheap probes. The envelope is
designed so an agent can act without a second call:

  * `rev` changes whenever anything observable changes -> stale-action protection
  * `legal` is the authoritative action list for this exact state
  * economy carries level_price, interest and the next interest breakpoint
  * capacity carries bench_free so a buy cannot silently fail
  * `round.label` maps the internal round number to the HUD label (e.g. 22 -> IV-6)
"""
from __future__ import annotations

from typing import Optional

import state as S
from bridge import Bridge

DEFAULT_SECTIONS = ('meta', 'economy', 'shop', 'bench', 'board', 'items',
                    'pending', 'bonds', 'timers', 'players', 'legality')

ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII']


def _try(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def round_label(n: int) -> Optional[str]:
    if n <= 0:
        return None
    stage = (n - 1) // 6 + 1
    sub = (n - 1) % 6 + 1
    return '%s-%s' % (ROMAN[stage - 1] if stage <= len(ROMAN) else stage, sub)


def interest_for(coin: int) -> int:
    return min(coin // 10, 5)


def next_breakpoint(coin: int) -> Optional[int]:
    if coin >= 50:
        return None
    return (coin // 10 + 1) * 10


class Observer:
    def __init__(self, bridge: Bridge):
        self.b = bridge
        self._was_in_match = False
        self._last_round = 0
        self._names: dict[int, Optional[str]] = {}
        self._bond_names: dict[int, Optional[str]] = {}
        self._bond_desc: dict[int, Optional[str]] = {}

    # ---- name resolution ----------------------------------------------
    def item_name(self, item_id: int) -> Optional[str]:
        """Resolve an equip id to its display name, cached per session."""
        if not item_id:
            return None
        if item_id in self._names:
            return self._names[item_id]
        r = _try(lambda: self.b.cfg('item', item_id), {}) or {}
        name = r.get('name')
        if name:
            self._names[item_id] = name
        return name

    def bond_name(self, bond_id: int) -> Optional[str]:
        """Resolve a synergy/bond id via CData_RelationSkillTip_MC.m_mRelationAttach."""
        if not bond_id:
            return None
        if bond_id in self._bond_names:
            return self._bond_names[bond_id]
        r = _try(lambda: self.b.call('CData_RelationSkillTip_MC',
                                     'GetValue_ByRelationId', bond_id), {}) or {}
        m = r.get('members') or {}
        name = m.get('m_mRelationAttach') or m.get('m_mRelationName') or None
        desc = m.get('m_mRelationExplain') or None
        if name:
            self._bond_names[bond_id] = name
        if desc:
            self._bond_desc[bond_id] = desc
        return name

    def bonds_named(self, bonds) -> list:
        out = []
        for b in bonds or []:
            try:
                bid = int(b.get('id'))
            except (TypeError, ValueError):
                bid = 0
            out.append({'id': bid or b.get('id'),
                        'name': self.bond_name(bid),
                        'value': b.get('value')})
        return out

    # ---- probes -------------------------------------------------------
    def load(self) -> S.Match:
        return S.parse(self.b.match())

    def auction_phase(self) -> Optional[str]:
        r = _try(lambda: self.b.probe(S.AUCTION), {}) or {}
        return (r.get('members') or {}).get('m_CurrPhase')

    def shop_refresh_cost(self, fallback: int) -> int:
        r = _try(lambda: self.b.probe(S.LBM + '.m_LogicHeroShop'), {}) or {}
        v = (r.get('members') or {}).get('refreshShopCost')
        try:
            return int(v)
        except (TypeError, ValueError):
            return fallback

    def gogo_state(self) -> dict:
        """Commander/GoGo prompt. The card list comes from the match payload's `gogo` block
        (names and descriptions resolved by the plugin); status and rerolls come from
        m_CurrData. Both are merged here so callers (guard, observe) see one shape."""
        raw = _try(lambda: (self.b.match() or {}).get('gogo'), None) or {}
        cards = raw.get('cards') or []
        if cards:
            return {'active': True, 'present': True,
                    'status': raw.get('status') or 'CanSelect',
                    'remaining_rerolls': raw.get('remaining'),
                    'max_cards': raw.get('maxCards'),
                    'cards': cards, 'counts': {}, 'flags': {}}
        r = _try(lambda: self.b.probe(S.GOGO), {}) or {}
        if not r.get('ok'):
            return {'active': False, 'present': False, 'status': None,
                    'remaining_rerolls': None, 'max_cards': None, 'cards': []}
        m = r.get('members') or {}
        cur = _try(lambda: self.b.probe(S.GOGO + '.m_CurrData'), {}) or {}
        cm = cur.get('members') or {}
        status = cm.get('m_Status')
        remain = cm.get('iRemainCount')
        try:
            remain = int(remain)
        except (TypeError, ValueError):
            remain = None
        active = bool(cm) and status not in (None, 'None', 'End', 'Finish')
        return {'active': active, 'present': True, 'status': status,
                'remaining_rerolls': remain,
                'max_cards': (lambda v: (int(v) if str(v).isdigit() else v))(m.get('m_iMaxCardCount')),
                'counts': {}, 'flags': {k: v for k, v in cm.items()
                                        if k in ('m_Status', 'iRemainCount', 'm_Quality')}}

    def _int(self, path: str) -> int:
        r = self.b.probe(path)
        try:
            return int(r.get('value'))
        except (TypeError, ValueError):
            return 0

    def crystal_state(self) -> dict:
        """The Choice Magic Crystal bond prompt (MCLogicVersatileCrystalComp).

        The component exists all the time, so presence is not the signal. The prompt is
        open while m_BondOptionIds holds options (m_bNeedCheck is the matching flag).
        The stale 'pending.crystal' we used to report came from presence alone."""
        out = {'active': False, 'present': False, 'options': [], 'component': 'MCLogicVersatileCrystalComp'}
        r = _try(lambda: self.b.probe(S.CRYSTAL + '.m_BondOptionIds.Count'), {}) or {}
        if not r.get('ok'):
            return out
        out['present'] = True
        try:
            count = int(r.get('value'))
        except (TypeError, ValueError):
            count = 0
        need = _try(lambda: self.b.probe(S.CRYSTAL + '.m_bNeedCheck'), {}) or {}
        need_flag = str(need.get('value')).lower() == 'true'
        if count <= 0 and not need_flag:
            return out
        ids = []
        for n in range(max(count, 0)):
            # the backing array is the only indexable path (verified live: _items[0] -> bond id)
            e = _try(lambda k=n: self.b.probe(S.CRYSTAL + f'.m_BondOptionIds._items[{k}]'), {}) or {}
            if e.get('ok'):
                try:
                    ids.append(int(e.get('value')))
                except (TypeError, ValueError):
                    pass
        out.update({'active': True, 'options': [{'id': b, 'name': self.bond_name(b)} for b in ids]})
        return out

    def auction_state(self, account: int = 0) -> dict:
        r = _try(lambda: self.b.probe(S.AUCTION), {}) or {}
        m = r.get('members') or {}
        phase = m.get('m_CurrPhase')
        active = bool(phase) and phase not in ('None', 'Idle', '')
        mine, turn = None, None
        if active and account:
            sel = _try(lambda: self.b.call(S.AUCTION, 'GetSelectItemIndexByAccId', account), {})
            bid = _try(lambda: self.b.call(S.AUCTION, 'GetBidIndexByAccId', account), {})
            try:
                mine = int((sel or {}).get('result'))
            except (TypeError, ValueError):
                mine = None
            try:
                turn = int((bid or {}).get('result')) if (bid or {}).get('ok') else None
            except (TypeError, ValueError):
                turn = None
        return {'active': active, 'phase': phase, 'my_index': mine, 'my_turn': turn}

    def welfare_state(self, raw: dict | None = None) -> dict:
        """Welfare reward selection (the turn-based pick after creep rounds).

        Each player is Locked (waiting), Unlocked (your turn) or Selected (already chose).
        Packs are the rewards on offer, keyed by slot. Read from the match payload.
        """
        w = (raw if raw is not None else (self.b.match() or {})).get('welfare') or {}
        if not w.get('active'):
            return {'active': False, 'phase': w.get('phase'), 'my_turn': False,
                    'my_state': w.get('myState'), 'packs': [], 'players': []}
        players = w.get('players') or []
        counts = {}
        for p in players:
            counts[p.get('state')] = counts.get(p.get('state'), 0) + 1
        return {'active': True, 'phase': w.get('phase'),
                'my_turn': bool(w.get('myTurn')), 'my_state': w.get('myState'),
                'packs': [{'slot': p.get('slot'), 'reward_id': p.get('rewardId'),
                           'name': p.get('heroName') or p.get('equipName'),
                           'kind': 'hero' if p.get('heroName') else ('equip' if p.get('equipName') else None)}
                          for p in (w.get('packs') or [])],
                'wants': w.get('wants') or [],
                'players_by_state': counts}

    def altar_state(self, account: int = 0) -> dict:
        """The 8-player altar selection (MCLogicAuctionComp). Read-only.

        phase      : None | PreWait | Prepare | Select | ResultWait | End
        my_turn    : True when this player is in the Select phase (their turn to choose)
        my_phase   : this player's own phase (None | Prepare | Select)
        items      : the altar items in order with current price, bidder and state
        """
        phase = self.auction_phase()
        active = bool(phase) and phase not in ('None', 'Idle', '')
        out = {'active': active, 'phase': phase, 'my_turn': False, 'my_phase': None,
               'my_index': None, 'remain_ms': None, 'items': []}
        if not active:
            return out
        for i in range(12):
            r = _try(lambda i=i: self.b.call(S.AUCTION, 'GetItemByIndex', i), {}) or {}
            if not r.get('ok') or r.get('result') in (None, 'None'):
                break
            mm = r.get('members') or {}
            out['items'].append({'index': i, 'active': mm.get('active'),
                                 'bid_price': S.oi(mm.get('m_iBidPrice')),
                                 'result_price': S.oi(mm.get('m_ResultPrice')),
                                 'bidder': mm.get('m_ulCurBidderAccId')})
        if account:
            p = _try(lambda: self.b.call(S.AUCTION, 'GetPlayerByAccId', account), {}) or {}
            pm = p.get('members') or {}
            my_phase = pm.get('m_CurrPhase')
            out['my_phase'] = my_phase
            out['my_turn'] = my_phase == 'Select'
            out['remain_ms'] = S.oi(pm.get('m_fRemainTime'))
            sel = _try(lambda: self.b.call(S.AUCTION, 'GetSelectItemIndexByAccId', account), {}) or {}
            out['my_index'] = S.oi(sel.get('result'))
        return out

    def timers(self) -> dict:
        rm = _try(lambda: self.b.probe(S.ROUND), {}) or {}
        mgr = _try(lambda: self.b.probe(S.LOGIC), {}) or {}
        rm_m, mgr_m = rm.get('members') or {}, mgr.get('members') or {}
        now = S.i(mgr_m.get('m_uiFrameTime'))
        phase = rm_m.get('m_eCurrentGamePhase')
        start = S.i(rm_m.get('m_uiStartPrpareTime'))
        end = None
        if phase == 'GamePhasePrepare':
            end = S.i(rm_m.get('m_uiStartFightCountDownTime'))
        elif phase == 'GamePhaseFightCountDown':
            start = S.i(rm_m.get('m_uiStartFightCountDownTime'))
            end = S.i(rm_m.get('m_uiStartFight'))
        elif phase == 'GamePhaseFight':
            start = S.i(rm_m.get('m_uiStartFight'))
        left = max(0, end - now) if (end and now) else None
        elapsed = max(0, now - start) if (start and now) else None
        # The round manager publishes the live countdown of the current phase directly
        # (RemaingTime / MaxRemaingTime, ms). Prefer it; the tick arithmetic is a fallback.
        remaining = S.oi(rm_m.get('RemaingTime'))
        total = S.oi(rm_m.get('MaxRemaingTime'))
        if remaining is not None and remaining >= 0:
            left = remaining
            if total:
                elapsed = max(0, total - remaining)
        return {'phase': phase, 'clock': now or None, 'start_tick': start or None,
                'end_tick': end, 'left_ms': left, 'elapsed_ms': elapsed,
                'total_ms': total or None}

    def players(self) -> list:
        d = _try(lambda: self.b._get('/deep', depth=2, cap=10), {}) or {}
        return d.get('players') or []

    # ---- envelope -----------------------------------------------------
    def build(self, sections=None, detail='summary', fmt='json',
              include_players=False, since_rev=None) -> dict:
        m = self.load()

        # round 0 = match over or still loading: report it as not seated and drop any
        # pending offers, which can be stale from the previous match
        if not m.in_match or m.round_no == 0:
            out = {'schema': 'mcgg.observe/v1', 'in_match': False}
            if self._was_in_match:
                out['ended'] = True
                out['last_round'] = self._last_round
                out['hint'] = 'match finished; result screen may still be open'
            else:
                out['hint'] = 'not seated; open a match'
            self._was_in_match = False
            return out

        self._was_in_match = True
        self._last_round = m.round_no

        rev = m.rev()
        if since_rev is not None and since_rev == rev:
            return {'schema': 'mcgg.observe/v1', 'rev': rev, 'unchanged': True}

        secs = tuple(sections) if sections else DEFAULT_SECTIONS
        full = detail == 'full'
        copies = m.copies()
        refresh = m.refresh_cost or self.shop_refresh_cost(0)
        auction = _try(self.auction_phase, None)
        altar_st = _try(lambda: self.altar_state(m.account), {'active': False, 'phase': None})
        raw_payload = m.raw or {}
        welfare_st = self.welfare_state(raw_payload)
        auction_st = altar_st
        gogo = _try(self.gogo_state, {'active': False, 'counts': {}})
        raw_gogo = (m.raw or {}).get('gogo') or {}
        if raw_gogo.get('cards') is not None:
            gogo = dict(gogo)
            gogo['cards'] = raw_gogo.get('cards')
            gogo['status'] = raw_gogo.get('status') or gogo.get('status')
            gogo['remaining_rerolls'] = raw_gogo.get('remaining', gogo.get('remaining_rerolls'))
            gogo['max_cards'] = raw_gogo.get('maxCards', gogo.get('max_cards'))
            gogo['active'] = bool(raw_gogo.get('status')) and raw_gogo.get('status') not in ('None', 'End')
        crystal = _try(self.crystal_state, {'active': False, 'counts': {}, 'flags': {}})
        out: dict = {'schema': 'mcgg.observe/v1', 'rev': rev}

        if 'meta' in secs:
            out['round'] = {'n': m.round_no, 'label': round_label(m.round_no),
                            'phase': m.phase, 'stage': m.stage,
                            'invade': m.invade, 'welfare': m.welfare,
                            'shopping': m.shopping, 'seated': m.seated}
            # the game's own board-capacity check (MCBehaviorThreeApi.CheckFullChessBoard)
            full = _try(lambda: str((self.b.act(op='api', method='CheckFullChessBoard', args=[]))
                                    .get('result')).lower() == 'true', None)
            out['capacity'] = {'board_full': full, 'board_units': len(m.board),
                               'bench_units': len(m.bench)}
        if 'economy' in secs:
            out['me'] = {'coin': m.coin, 'level': m.level, 'level_price': m.level_price,
                         'hp': m.hp, 'hp_max': m.hp_max,
                         'population': m.population, 'pop_max': m.pop_max,
                         'power': m.power(), 'interest': interest_for(m.coin),
                         'next_interest_at': next_breakpoint(m.coin),
                         'account': m.account}
        if 'shop' in secs:
            slots = []
            for s in m.shop:
                have = copies.get(s.name or '', 0)
                e = {'slot': s.slot, 'name': s.name, 'cost': s.cost, 'owned': have}
                if have == 2:
                    e['makes'] = '2*'
                elif have == 1:
                    e['makes'] = 'pair'
                slots.append(e)
            # free refreshes: MCChessPlayerData.m_RefreshShopFreeTimes (int3 x/y/z).
            # Which field is the remaining count is confirmed against the on-screen "FREE xN".
            # the game's own remaining-free-refresh count (the number behind the "FREE xN" label)
            free = _try(lambda: int(self.b.call(f'{S.LBM}.m_PlayerData', 'GetFreeFreshShopCount4Show')
                                    .get('result') or 0), None)
            out['shop'] = {'refresh_cost': refresh, 'locked': m.locked,
                           'bench_free': max(0, 9 - len(m.bench)), 'slots': slots,
                           'free_refresh_remaining': free}
        if 'bench' in secs:
            out['bench'] = [{'slot': b.slot, 'guid': b.guid, 'name': b.name, 'star': b.star}
                            for b in m.bench]
        if 'board' in secs:
            grid = [['.'] * 7 for _ in range(6)]
            for u in m.board:
                if u.name and 0 <= u.x < 7 and 0 <= u.y < 6:
                    grid[u.y][u.x] = u.name[0] + str(u.star or 1)
            board = {'w': 7, 'h': 6,
                     'units': [{'guid': u.guid, 'name': u.name, 'star': u.star,
                                'x': u.x, 'y': u.y, 'items': u.items}
                               for u in m.board if u.name]}
            if full:
                board['grid'] = [''.join(r) for r in grid]
            out['board'] = board
        if 'items' in secs:
            by_guid = {u.guid: u.name for u in m.board}
            out['items'] = {
                'bag': [{'guid': x.guid, 'id': x.item_id,
                         'name': x.name or self.item_name(x.item_id), 'upgrade': x.upgrade}
                        for x in m.free_items()],
                'on': [{'guid': x.guid, 'id': x.item_id,
                        'name': x.name or self.item_name(x.item_id), 'slot': x.slot,
                        'owner': by_guid.get(x.owner), 'owner_guid': x.owner}
                       for x in m.items if x.owner],
            }
        if 'pending' in secs:
            pend = {}
            if m.offers:
                def _pick_item(i_):
                    iid = (i_.get('raw') or {}).get('m_iItemParam1') or 0
                    try:
                        iid = int(iid)
                    except (TypeError, ValueError):
                        iid = 0
                    return {'id': iid, 'name': i_.get('name') or self.item_name(iid)}

                pend['pick'] = [{'guid': o.get('guid'),
                                 'items': [_pick_item(i_) for i_ in (o.get('items') or [])]}
                                for o in m.offers]
            wel = self.welfare_state(raw_payload)
            if wel.get('active'):
                pend['welfare'] = wel
            if altar_st.get('active'):
                pend['altar'] = {'phase': altar_st.get('phase'),
                                 'my_turn': altar_st.get('my_turn'),
                                 'my_phase': altar_st.get('my_phase'),
                                 'my_index': altar_st.get('my_index'),
                                 'remain_ms': altar_st.get('remain_ms'),
                                 'items': altar_st.get('items')}
            if gogo.get('active'):
                pend['gogo'] = {'status': gogo.get('status'),
                                'remaining_rerolls': gogo.get('remaining_rerolls'),
                                'max_cards': gogo.get('max_cards'),
                                'cards': gogo.get('cards')}
            if crystal.get('active'):
                pend['crystal'] = {'component': crystal.get('component'),
                                   'options': crystal.get('options')}
            out['pending'] = pend or {'none': True}
        if 'bonds' in secs and m.bonds:
            out['bonds'] = self.bonds_named(m.bonds)
        if 'timers' in secs:
            t = self.timers()
            out['timers'] = t if full else {'left_ms': t.get('left_ms'), 'phase': t.get('phase')}
        if 'players' in secs or include_players:
            pl = self.players()
            if full or include_players:
                out['players'] = [{'acc': p.get('accId'), 'coin': p.get('coin'),
                                   'hp': p.get('hp'), 'units': p.get('units'),
                                   'self': p.get('accId') == m.account,
                                   'board': [c.get('name') for c in (p.get('composition') or [])]}
                                  for p in pl]
            else:
                out['players'] = [{'acc': p.get('accId'), 'hp': p.get('hp'),
                                   'units': p.get('units'), 'self': p.get('isSelf')}
                                  for p in pl]
        if 'legality' in secs:
            out['legal'] = legal_actions(
                m,
                gogo_active=bool(gogo.get('active')),
                crystal_active=bool(crystal.get('active')),
                auction_active=bool(auction_st.get('active')),
                welfare_active=bool(welfare_st.get('active')))

        return out if fmt == 'json' else {'text': render_text(out, m)}


def legal_actions(m: S.Match, gogo_active: bool = False,
                  crystal_active: bool = False, auction_active: bool = False,
                  welfare_active: bool = False) -> list:
    if not m.in_match:
        return []
    acts = ['observe', 'wait_for']
    # the pick prompt can appear in any phase, including during combat
    acts.append('pick_item')
    if gogo_active:
        acts += ['gogo_select', 'gogo_reroll']
    if crystal_active:
        acts.append('crystal_select')
    if welfare_active:
        acts.append('welfare_pick')   # the guard waits for the turn and checks it
    if not auction_active:
        if m.shop:
            acts.append('buy_hero')
            acts.append('lock_shop')
        if m.coin >= 1 and m.shop:
            acts.append('reroll_shop')
        if m.level_price and m.coin >= m.level_price:
            acts.append('buy_xp')
        if m.bench or m.board:
            acts.append('sell_hero')
        if m.free_items():
            acts.append('equip')
            if m.shopping and any(u.name for u in m.board):
                acts.append('equip_best')
        if any(x.owner for x in m.items) and m.shopping:
            acts.append('unequip')
        if m.shopping:
            acts += ['move_to_cell', 'move_to_bench', 'swap_bench', 'auto_deploy']
    return sorted(set(acts))


def render_text(o: dict, m: S.Match) -> str:
    lines = []
    r = o.get('round') or {}
    left = ((o.get('timers') or {}).get('left_ms') or 0) // 1000
    lines.append('R%s (%s) | %s | %ss left' % (
        r.get('n'), r.get('label'), (r.get('phase') or '').replace('GamePhase', ''), left))
    me = o.get('me') or {}
    lines.append('me: %sg | L%s(%sg) | HP %s/%s | power %s | interest %s'
                 % (me.get('coin'), me.get('level'), me.get('level_price'),
                    me.get('hp'), me.get('hp_max'), me.get('power'), me.get('interest')))
    slots = (o.get('shop') or {}).get('slots') or []
    if slots:
        lines.append('shop: (refresh %sg, bench free %s)'
                     % ((o.get('shop') or {}).get('refresh_cost'),
                        (o.get('shop') or {}).get('bench_free')))
        for s in slots:
            tag = '  -> %s' % s['makes'] if s.get('makes') else ''
            lines.append('  [%s] %-10s %sg q%s%s' % (s['slot'], s['name'], s['cost'], s['quality'], tag))
    bench = o.get('bench') or []
    if bench:
        lines.append('bench: ' + ' | '.join('%s %s* (%s)' % (b['name'], b['star'], b['slot'])
                                            for b in bench[:9]))
    units = (o.get('board') or {}).get('units') or []
    if units:
        lines.append('board: ' + ' | '.join('%s %s* (%s,%s)' % (u['name'], u['star'], u['x'], u['y'])
                                            for u in units[:12]))
    items = o.get('items') or {}
    if items.get('bag') or items.get('on'):
        bag = ', '.join('%s %s' % (x['id'], x['name']) for x in items.get('bag') or [])
        on = ', '.join('%s: %s' % (x['owner'], x['name']) for x in items.get('on') or [])
        lines.append('items: bag %s | on %s' % (bag or 'none', on or 'none'))
    pend = o.get('pending') or {}
    lines.append('pending: ' + ('none' if pend.get('none') else ', '.join(pend)))
    bonds = o.get('bonds') or []
    if bonds:
        lines.append('bonds: ' + ' | '.join(
            '%s %s' % (b.get('name') or ('#' + str(b.get('id'))), b.get('value'))
            for b in bonds))
    players = o.get('players') or []
    if players:
        lines.append('players: ' + ' '.join('%s%s' % (p.get('acc'), '*' if p.get('self') else '')
                                            for p in players))
    lines.append('legal: ' + ' '.join(o.get('legal') or []))
    return '\n'.join(lines)