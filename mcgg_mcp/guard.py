"""Legality engine + action execution.

Scope: local, single-operator automation of the operator's own game client. Every action
maps to a method the game's UI itself calls, so the game's own rules and validations apply.

Every mutation is checked against the *current* state (not the state the caller saw),
optionally against an expected `rev`, and — for actions whose success is not visible in
their return value — verified afterwards.

Denial shape:
    {"ok": false,
     "error": {"code": "...", "message": "...", "hint": "...", "legal": [...]}}
"""
from __future__ import annotations

import time

import state as S
from bridge import Bridge, BridgeError
from observe import Observer, legal_actions

BOARD_TOOLS = {'move_to_cell', 'move_to_bench', 'swap_bench', 'auto_deploy'}
# answers to forced prompts; exempt from the per-minute action budget
PROMPT_TOOLS = {'pick_item', 'crystal_select', 'gogo_select', 'welfare_pick'}
ALTAR_BLOCKED = {'buy_hero', 'reroll_shop', 'sell_hero', 'lock_shop',
                 'move_to_cell', 'move_to_bench', 'swap_bench', 'auto_deploy'}


class FullError(ValueError):
    """The board or bench has no room. Reported as HERO_SLOTS_FULL, not as a silent no-op."""


class LockedError(ValueError):
    """The action is valid only in a shopping phase. Reported as PHASE_LOCKED."""


class Engine:
    def __init__(self, bridge: Bridge, observer: Observer,
                 dry_run: bool = False, max_per_minute: int = 30):
        self.b = bridge
        self.o = observer
        self.dry_run = dry_run
        self.max_per_minute = max_per_minute
        self.stamps: list[float] = []

    # ---- helpers ------------------------------------------------------
    def _rate_ok(self) -> bool:
        now = time.time()
        self.stamps = [s for s in self.stamps if now - s < 60]
        return len(self.stamps) < self.max_per_minute

    def _deny(self, code: str, message: str, hint: str, m: S.Match | None,
              extra: dict | None = None) -> dict:
        err = {'code': code, 'message': message, 'hint': hint,
               'legal': legal_actions(m) if m else []}
        if extra:
            err.update(extra)
        return {'ok': False, 'error': err}

    def _board_full(self) -> bool:
        """MCBehaviorThreeApi.CheckFullChessBoard(): the game's own board-capacity check."""
        r = self.b.act(op='api', method='CheckFullChessBoard', args=[])
        return str(r.get('result')).lower() == 'true'

    def _altar_active(self) -> bool:
        p = self.o.auction_phase()
        return bool(p) and p not in ('None', 'Idle', '')

    # ---- entry point ---------------------------------------------------
    def run(self, tool: str, args: dict) -> dict:
        m = self.o.load()

        # round 0 means the match is over or still loading (stale pending state is ignored)
        if not m.in_match or m.round_no == 0:
            return self._deny('NOT_SEATED', 'not in a match (match over or loading)',
                              'wait for wait_for(in_match=true) or start a match', m)

        expect = args.get('expect_rev')
        if expect is not None and int(expect) != m.rev():
            return self._deny('STALE_REV', 'state changed since that observation',
                              'call observe again, then retry', m,
                              {'expected': int(expect), 'actual': m.rev()})

        # A blocking item offer must be resolved before anything else is accepted.
        if m.offers and tool not in ('pick_item', 'welfare_pick', 'observe', 'wait_for', 'help'):
            return self._deny('PICK_PENDING', f'{len(m.offers)} item offer(s) must be resolved first',
                              'call pick_item for each offer in observe().pending.pick', m)

        if tool in BOARD_TOOLS and not m.shopping:
            return self._deny('PHASE_LOCKED', 'board changes are locked during combat',
                              "wait_for(phase='GamePhasePrepare')", m)

        if tool in ALTAR_BLOCKED and self._altar_active():
            return self._deny('ALTAR_ACTIVE', 'altar phase is running',
                              'wait_for(altar_free=True)', m)

        if tool not in legal_actions(m,
                                     gogo_active=bool(self.o.gogo_state().get('active', False)),
                                     crystal_active=bool(self.o.crystal_state().get('active', False)),
                                     auction_active=self._altar_active(),
                                     welfare_active=bool(self.o.welfare_state(m.raw).get('active'))):
            return self._deny('NOT_LEGAL', f'{tool} is not legal in {m.phase}',
                              'read observe().legal', m)

        # Prompt answers (offers, crystal, GoGo cards, welfare) are forced decisions that
        # unblock the game, so a burst of them must not trip the action budget.
        counted = tool not in PROMPT_TOOLS
        if counted and not self._rate_ok():
            return self._deny('RATE_LIMIT', f'{self.max_per_minute} actions/min exceeded',
                              'slow down', m)

        try:
            res, verified = self._execute(tool, args, m)
        except KeyError as e:
            return self._deny('BAD_ARGUMENT', f'missing argument {e}', 'check the schema', m)
        except FullError as e:
            return self._deny('HERO_SLOTS_FULL', str(e), 'free a slot, then retry', m)
        except LockedError as e:
            return self._deny('PHASE_LOCKED', str(e), "wait_for(phase='GamePhasePrepare')", m)
        except ValueError as e:
            return self._deny('BAD_ARGUMENT', str(e), 'check observe()', m)
        except BridgeError as e:
            return self._deny('BRIDGE_ERROR', str(e), 'is the game running?', m)
        except Exception as e:                      # noqa: BLE001
            return self._deny('INTERNAL', f'{type(e).__name__}: {e}', 'report this', m)

        if counted:
            self.stamps.append(time.time())

        # A verified state change is the ground truth. The bridge's `ok` flag is only a
        # hint: the game often applies a call a moment later (level-up) and the bridge
        # reports the immediate return value, so a verified change wins over `ok: false`.
        if verified is True:
            # the bridge's own ok/tried flags can read false for a call that did apply
            # (level-up); the verified state is what counts, so drop them
            clean = {k: v for k, v in res.items() if k not in ('ok', 'tried')} if isinstance(res, dict) else res
            return {'ok': True, 'result': clean or None, 'rev': self.o.load().rev()}

        if verified is False:
            return self._deny('NO_EFFECT', 'the game accepted the call but nothing changed',
                              self._no_effect_hint(tool, m), m, {'result': res})

        # verified is None: the action has no observable effect we can read back
        if not res.get('ok'):
            return self._deny('GAME_REJECTED', str(res.get('error') or res.get('result') or res),
                              'read the result payload', m, {'result': res})

        return {'ok': True, 'result': res, 'rev': self.o.load().rev()}

    @staticmethod
    def _no_effect_hint(tool: str, m: S.Match) -> str:
        if tool == 'buy_hero':
            return ('the shop/bench is probably full ("Hero Slots are full"); '
                    'sell a weak unit first, then retry')
        if tool == 'equip':
            return 'the item did not move; check the hero slot (1-3) and that the phase is not combat'
        return 'observe again; the action may require a different target'

    # ---- readback helpers ---------------------------------------------------
    def _poll(self, check, tries: int = 8, pause: float = 0.25) -> bool:
        """Re-read state until check(after) is true or the budget runs out."""
        for _ in range(tries):
            time.sleep(pause)
            if check(self.o.load()):
                return True
        return False

    # ---- execution -----------------------------------------------------
    def _execute(self, tool: str, a: dict, m: S.Match):
        """Returns (result, verified) where verified None means 'not checkable'."""
        if self.dry_run:
            return {'ok': True, 'dry_run': True, 'would': {tool: a}}, None

        if tool == 'buy_hero':
            slot = int(a['slot'])
            entry = next((s for s in m.shop if s.slot == slot), None)
            if entry is None:
                raise ValueError(f'no shop slot {slot}')
            if entry.cost > m.coin:
                raise ValueError(f'costs {entry.cost}, have {m.coin}')
            if not entry.name:
                raise ValueError(f'slot {slot} is empty')
            res = self.b.buy(slot)
            # verify: the price left the purse or the slot now holds something else
            def bought(after):
                e = next((s for s in after.shop if s.slot == slot), None)
                return after.coin < m.coin or e is None or e.hero_id != entry.hero_id
            return res, self._poll(bought, tries=8, pause=0.25)

        if tool == 'sell_hero':
            guid = int(a.get('hero_guid') or 0)
            slot = a.get('bench_slot')
            if slot is not None and not m.shopping:
                raise LockedError('bench units can only be sold while shopping (verified: '
                                  'the game refuses bench sells in combat)')
            if guid:
                # LogicBattleManager.SellHero(uint heroGuid, bool isManual, bool gainCoin,
                #                              bool bySell, SellHeroType sellType)
                # the game exposes only the 5-argument overload; all defaults are passed.
                res = self.b.call(S.LBM, 'SellHero', guid, 'true', 'true', 'true', 0)
                target = next((u for u in m.board if u.guid == guid), None) \
                    or next((b for b in m.bench if b.guid == guid), None)
                coin0 = m.coin
                return res, self._poll(lambda after: after.coin > coin0
                                       or (target is not None and
                                           not any(u.guid == guid for u in after.board)
                                           and not any(b.guid == guid for b in after.bench)),
                                       tries=8, pause=0.25)
            if slot is not None:
                # The shop-level SellHero(heroId, star) does not remove bench units (verified:
                # NO_EFFECT), so resolve the bench slot to its guid and use the guid path.
                entry = next((b for b in m.bench if b.slot == int(slot)), None)
                if entry is None:
                    raise ValueError(f'no bench slot {slot}')
                if not entry.guid:
                    raise ValueError('bench slot has no hero guid')
                return self._execute('sell_hero', {'hero_guid': entry.guid}, m)
            raise ValueError('need hero_guid or bench_slot')

        if tool == 'reroll_shop':
            if not m.shop:
                raise ValueError('shop is closed right now')
            before = [(s.slot, s.hero_id) for s in m.shop]
            coin0 = m.coin
            # Logic-layer refresh: works whether or not the shop panel is on screen.
            # Falls back to the panel key path when the logic call is unavailable.
            res = self.b.call(S.LBM + '.m_LogicHeroShop', 'RefreshShop')
            if not res.get('ok'):
                res = self.b.refresh()
            def refreshed(after):
                return after.coin < coin0 or [(s.slot, s.hero_id) for s in after.shop] != before
            return res, self._poll(refreshed, tries=8, pause=0.25)

        if tool == 'buy_xp':
            price = m.level_price or 0
            if price and m.coin < price:
                raise ValueError(f'level costs {price}, have {m.coin}')
            res = self.b.act(op='levelup')
            # the game applies the level change asynchronously
            def leveled(after):
                # only a level increase proves the level-up; a coin drop can come from
                # another action (reroll, buy) and must not count as success
                return after.level > m.level
            return res, self._poll(leveled, tries=16, pause=0.25)

        if tool == 'lock_shop':
            want = bool(a.get('locked', True))
            return self.b.call(S.LBM + '.m_LogicHeroShop', 'SetLockShop', want), None

        if tool == 'auto_deploy':
            before = {(u.guid, u.x, u.y) for u in m.board}
            bench0 = len(m.bench)
            res = self.b.deploy()
            def deployed(after):
                return {(u.guid, u.x, u.y) for u in after.board} != before or len(after.bench) != bench0
            return res, self._poll(deployed, tries=6, pause=0.25)

        if tool == 'move_to_cell':
            guid, x, y = int(a['hero_guid']), int(a['x']), int(a['y'])
            if not (0 <= x < 7 and 0 <= y < 6):
                raise ValueError('cell outside 7x6')
            # observed in live prep: the game refuses rows 3-5 (they are the enemy-side
            # rows the battle layout uses), so reject them here instead of a silent NO_EFFECT
            if m.shopping and y > 2:
                raise ValueError(f'prep placement is limited to rows 0-2; (x,y) = ({x},{y}) is outside it')
            if any(u.x == x and u.y == y and u.guid != guid for u in m.board):
                raise ValueError(f'cell ({x},{y}) is occupied')
            on_board = any(u.guid == guid for u in m.board)
            if on_board:
                # MoveHeroInBattleField(uint instanceId, byte x, byte y, bool bIsAi)
                res = self.b.call(S.LBM, 'MoveHeroInBattleField', guid, x, y, 'false')
            else:
                # bench -> board: MoveHeroToBattleField(uint, byte, byte, bool byAI, bool bIsAIApi)
                if not any(b.guid == guid for b in m.bench):
                    raise ValueError('hero is neither on the board nor on the bench')
                if self._board_full():
                    raise FullError('the board is full ("Hero Slots are full"); '
                                    'sell or move a unit to the bench first, or level up')
                res = self.b.call(S.LBM, 'MoveHeroToBattleField', guid, x, y, 'false', 'false')
            def placed(after):
                u = next((u for u in after.board if u.guid == guid), None)
                return u is not None and u.x == x and u.y == y
            if self._poll(placed, tries=6, pause=0.25):
                return res, True
            # the board list can lag behind a move the game accepted; only a bridge
            # refusal counts as NO_EFFECT, otherwise report the move as unverified
            accepted = str(res.get('result')).lower() == 'true'
            return res, (None if accepted else False)

        if tool == 'move_to_bench':
            guid = int(a['hero_guid'])
            used = {b.slot for b in m.bench}
            # slot is optional: default to the lowest free bench slot
            slot = int(a['slot']) if a.get('slot') is not None else                 next((s_ for s_ in range(1, 10) if s_ not in used), None)
            if slot is None:
                raise FullError('the bench is full')
            if not (1 <= slot <= 9):
                raise ValueError('bench slot must be 1-9')
            if not any(u.guid == guid for u in m.board):
                raise ValueError('hero is not on the board')
            # MoveHeroToReserve(uint guid, byte slotId, bool isTreatHero, bool bIsAIApi)
            res = self.b.call(S.LBM, 'MoveHeroToReserve', guid, slot, 'false', 'false')
            def benched(after):
                # the hero is on the bench; the board copy can lag a moment behind
                return any(b.guid == guid for b in after.bench)
            return res, self._poll(benched, tries=10, pause=0.25)

        if tool == 'swap_bench':
            f, t = int(a['from_slot']), int(a['to_slot'])
            before = {b.slot: b.guid for b in m.bench}
            res = self.b.call(S.LBM, 'MoveHeroInReserve', f, t, 'false')
            def swapped(after):
                now = {b.slot: b.guid for b in after.bench}
                return now.get(f) != before.get(f) or now.get(t) != before.get(t)
            return res, self._poll(swapped, tries=6, pause=0.25)

        if tool == 'equip':
            item, hero = int(a['item_guid']), int(a['hero_guid'])
            res = self.b.equip(item, hero, int(a.get('slot', 1)))
            after = self.o.load()
            moved = next((x for x in after.items if x.guid == item), None)
            verified = bool(moved and moved.owner == hero)
            if not verified:
                # Choice Magic Crystal transforms into a new versatile-crystal guid,
                # so the bag guid cannot be used to verify; trust the game's slot result.
                api_ok = bool(res.get('ok')) and str(res.get('result')) not in ('False', 'false')
                verified = api_ok and res.get('newSlot') is not None
            return res, verified

        if tool == 'equip_best':
            target = max((u for u in m.board if u.name),
                         key=lambda u: ((u.star or 1), (u.quality or 1)))
            out, used, placed = [], len(target.items), 0
            for it in m.free_items():
                used += 1
                if used > 3:
                    break
                r = self.b.equip(it.guid, target.guid, used)
                out.append(r)
                if r.get('ok'):
                    placed += 1
            return {'ok': placed > 0, 'hero': target.name, 'placed': placed, 'results': out}, None

        if tool == 'unequip':
            item = int(a['item_guid'])
            owner = next((x.owner for x in m.items if x.guid == item), 0)
            if not owner:
                raise ValueError('item is not equipped on a hero')
            res = self.b.act(op='unequip', item=item)
            def bagged(after):
                it = next((x for x in after.items if x.guid == item), None)
                return it is not None and not it.owner
            return res, self._poll(bagged, tries=6, pause=0.25)

        if tool == 'pick_item':
            guid = int(a['offer_guid'])
            idx = int(a.get('index', 0))
            before = {int(o.get('guid') or 0) for o in m.offers}
            # LogicChessPickMgr.OnPickDistributeRes(guid, index) is the real pick
            res = self.b.call(S.PICK, 'OnPickDistributeRes', guid, idx)
            after = self.o.load()
            gone = guid not in {int(o.get('guid') or 0) for o in after.offers}
            if not gone and before == {int(o.get('guid') or 0) for o in after.offers}:
                # fall back to the auto-distribute helpers
                if res.get('ok') is False:
                    res = self.b.act(op='api', method='TryDistributeMagicCrystal', args=[0])
            return res, gone

        if tool == 'welfare_pick':
            # Clicks the reward card on screen the moment the turn opens: no screenshot or
            # reasoning round trip (a turn lasts about 7 s). Tries cards in preference order and
            # verifies the pick by the Selected state after each click.
            import clicker
            budget = float(a.get('wait_s', 25))
            order = [a['card']] if a.get('card') else list(clicker.WELFARE_CARDS)
            end = time.time() + budget
            while True:
                wel = self.o.welfare_state()
                if wel.get('my_turn') or time.time() >= end:
                    break
                time.sleep(0.05)
            if not wel.get('active'):
                raise LockedError('no welfare reward selection is running')
            if not wel.get('my_turn'):
                raise LockedError(f"it was not your turn within {budget:g}s (your state: "
                                  f"{wel.get('my_state')})")
            tried = []
            for name in order:
                if name not in clicker.WELFARE_CARDS:
                    raise ValueError(f'unknown card {name}')
                x, y = clicker.WELFARE_CARDS[name]
                clicker.click_shot_point(x, y)
                tried.append(name)
                time.sleep(0.25)
                now = self.o.welfare_state()
                if now.get('my_state') == 'Selected':
                    return {'ok': True, 'result': {'card': name, 'tried': tried}}, True
                if not now.get('my_turn'):
                    break
            return {'ok': False, 'result': {'tried': tried}}, False

        if tool == 'crystal_select':
            idx = int(a['index'])
            def crystal_id():
                try:
                    r = self.b.probe(S.CRYSTAL) or {}
                    return int((r.get('members') or {}).get('m_iVersatileCrystalId') or 0)
                except (TypeError, ValueError):
                    return 0
            before = crystal_id()
            # versatile (Choice Magic Crystal) prompt: OnSelectBond(index) on the comp
            res = self.b.call(S.CRYSTAL, 'OnSelectBond', idx)
            if not res.get('ok'):
                # super-crystal 3-choice prompt uses the behaviour API
                res = self.b.act(op='api', method='PickedSuperCrystal', args=[idx])
            after = crystal_id()
            # during combat the comp can keep m_iVersatileCrystalId, so trust a clean call
            changed = bool(res.get('ok')) and str(res.get('result')) not in ('False', 'false')
            if not changed:
                changed = (before != 0 and after == 0) or (before != after)
            return res, changed

        if tool == 'gogo_reroll':
            idx = int(a.get('index', 0))
            before = self.o.gogo_state()
            # ReRandomCard(index, eGoGoCardReRandomType.Normal == 1) is the free refresh;
            # it internally calls PaidDiceComp.OnReRandomCard and ModifyCardList.
            res = self.b.call(S.GOGO, 'ReRandomCard', idx, 1)
            after = self.o.gogo_state()
            changed = (after.get('remaining_rerolls') != before.get('remaining_rerolls')
                       or after.get('status') != before.get('status')
                       or after.get('active') != before.get('active')
                       or after.get('cards') != before.get('cards'))
            return res, changed

        if tool == 'gogo_select':
            before = self.o.gogo_state()
            cards = before.get('cards') or []
            if a.get('index') is not None:
                idx = int(a.get('index'))
                if idx < 0 or idx >= len(cards):
                    return {'ok': False,
                            'error': {'code': 'BAD_ARGUMENT',
                                      'message': f'index {idx} out of range ({len(cards)} cards)',
                                      'hint': 'read observe().pending.gogo.cards'}}, False
                cid = cards[idx].get('id')
                # SelectCard(cardId, slotIndex, forceAdd) - takes the card at that slot
                res = self.b.call(S.GOGO, 'SelectCard', cid, idx, 'false')
            else:
                mode = int(a.get('mode', 0))
                res = self.b.act(op='api', method='TrySelectGoGoCard', args=[mode])
                if not res.get('ok'):
                    res = self.b.call(S.GOGO, 'TrySelectGoGoCard', mode)
            after = self.o.gogo_state()
            changed = (not after.get('active')) or after.get('status') != before.get('status') \
                      or after.get('cards') != before.get('cards')
            return res, changed

        raise ValueError(f'no handler for {tool}')