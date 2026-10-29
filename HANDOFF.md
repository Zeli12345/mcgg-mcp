# Handoff: mcgg-mcp and the Magic Chess GoGo session

Written 2026-10-29 at the end of a long play session. It records what was known at the time, what was
changed in code, what is still broken, and what the next player (human or agent) should check first.
Treat every game-state number here as a snapshot, not as a current reading.

## 1. Where things stand

- **Game state at the end:** the last match was seated but the bridge dropped mid-round. The final
  readable state was round II-4 (prep then fight). Gold 86, interest +5 (capped), level 6, HP 88/100.
  Board: Martis ★1 (Purify), Phoveus ★2, Saber ★1 x2 (Sea Halberd and Golden Staff on one), Paquito ★1,
  Granger ★1 at (2,0) with the Choice Magic Crystal. Bench: Tigreal ★1 (not placed; the board was full),
  Minotaur x2, Granger ★1, Phoveus ★1, Yi Sun-shin ★1, Angela ★1. Pending prompt at the time of the drop:
  the Choice Magic Crystal bond choice on Granger (options SPECTRE, Marksman, Bruiser). Marksman (index 1)
  was intended but was not confirmed.
- **Earlier match (round I-4):** gold 27, interest +2, level 4. Granger ★1 with Inspire at (3,1),
  Edith ★1 at (4,1), Hylos ★1 at (4,2), Zhuxin ★1 at (3,0). Shop had Martis, Belerick, Eudora (no lineup).
- **Whether the match is still running is unknown.** The bridge was unreachable at the time of writing.
- **Code:** the repo at `C:\Users\satya\Downloads\mcgg-mcp` now has the same files as the running copy at
  `C:\Users\satya\Downloads\New folder (53)\mcgg-mcp`. 40 tests pass in both. Changes are on a branch
  and pushed (see section 6).

## 2. The lineup and the plan

- **Lineup:** 6-Marksman and 4-Defender, applied from Lineup > Recommended Lineups > Use (shows "Saved").
- **Marksman heroes:** Granger, Irithel, Karrie, Melissa, Miya, Wanwan.
- **Defender heroes:** Atlas, Baxia, Edith, Hylos, Minotaur, Tigreal.
- **Breakpoints:** Marksman 2/4/6 gives ATK speed +5/+10/+20%. Defender 2/4/6 gives all allies +6/+12/+24
  hybrid DEF.
- **User preferences (in their words):**
  - Play properly, follow a plan each prep, and avoid `equip_best` and `auto_deploy` where possible.
    Decide equips manually.
  - From level 8 to 9, roll the shop to make 2★ and 3★ copies of lineup heroes. Do not hoard gold above
    the interest cap of 50.
  - Prefer higher-tier Attackers and Defenders (3-, 4- and 5-cost) over common 1–2-cost units, but not
    exclusively.
  - Use winput only outside matches (menus, lobby, result screen). During a match use only the mcgg tools.
  - Ask before any purchase, sending messages, deleting data or entering credentials or payment details.
  - Never click Purchase Pass, the rebate "Get" button, Report or Share.
  - Do not try to get around anti-cheat or input filtering. If input is ignored, report it and stop.

## 3. Mechanics learned (verified in play unless marked)

- **Phases:** GamePhasePrepare (shopping), GamePhaseForecast, GamePhaseWelfare, GamePhaseFight,
  GamePhaseFightCountDown, GamePhaseFightResult.
- **Board:** 7 columns by 6 rows. Prep placement is rows 0–2 only; rows 3–5 are refused. The `observe`
  grid string lists cells in row order.
- **Capacity:** level-driven. Level 4 seemed to allow 4 board units, level 5 about 5, level 6 about 6.
  Bench has 9 slots. Board plus bench is capped; at the cap, buys return NO_EFFECT with "Hero Slots are full".
- **Interest:** +1 per 10 gold held at round end, up to +5 at 50. Gold above 50 earns nothing, so spend it.
  Observed: 20–29 gives +2 and 30–39 gives +3, consistent with the table in CLAUDE.md.
- **Level-up cost:** shown as `level_price` in observe. It varied a lot (3, 1, 5, 7, 13, 15, 17, 32),
  so read it from the screen each time. At level 4, `buy_xp` returned NO_EFFECT at 5 gold and did not
  level (observed once; unresolved).
- **Free refresh:** `refresh_cost` was 0 at II-3 and II-4 (free rerolls). Normally 2 gold. Read it
  before rolling.
- **Pending prompts block shopping:** item picks (`pick_item`) and the Go Go card (`gogo_select`) must be
  resolved before buy, sell and move calls work. The shop can close while a prompt is still open.
- **Item picks during the fight:** `pick_item` returned NO_EFFECT during the fight, but worked in the
  following prep. Resolve picks early in prep.
- **Auto-equip:** the game auto-equips a picked item onto a unit. Golden Staff landed on Saber, not a
  carry. Check the equip result after each pick.
- **Board sync quirk:** `observe`'s board list sometimes omitted a unit that the `players` entry showed
  on the board (Hylos at I-3). It reappeared a few seconds later. Do not act on a unit's absence until a
  second observe confirms it.
- **Merges:** 3 copies make ★2 and 3 ★2 make ★3. `makes: "pair"` or `makes: "2*"` in the shop marks a buy
  that completes a merge.
- **Crystal:** a Choice Magic Crystal goes to the crystal slot (shown as slot 4) and then asks for a bond
  through `crystal_select`. Options come from the response (e.g. SPECTRE, Marksman, Bruiser). Confirm the
  pick before the round changes; a round change can make the prompt stale (STALE_REV).
- **Crystal moves:** equipping a second Choice crystal to another hero moved the existing one, which
  dropped the previous hero's bond. Avoid it unless intended.
- **Unequip:** removing a crystal needs `confirm_bond_loss: true`.

## 4. Code state

Repo `mcgg-mcp` (module `mcgg_mcp`), local server for one running client. Tools are listed in README.md.

### Fixes made this session (all in both copies)

- `observe.py`:
  - `render_text` uses `.get` for missing fields and drops the quality field from the text line
    (fixed a `KeyError: 'quality'`).
  - `economy` adds `idle_gold` (gold above 50).
  - `legal_actions` gates buy, lock, reroll and buy_xp on `m.shopping`, and gates equip on free items
    plus shopping.
  - `item_name(item_id)` maps item ids to names.
- `state.py`:
  - `parse()` drops board units whose `accountId` is nonzero and differs from the local account.
  - `rev()` uses a narrower signature during fights (fixes STALE_REV spam). When shopping, it includes
    item guid, owner and slot.
- `guard.py`:
  - `is_crystal(name)` is a module-level helper.
  - `Engine._name(x)` falls back to `observer.item_name(item_id)` when a name is missing (the live fix for
    `slot 1 already holds None`). Added in this session's last pass.
  - `_equip` refuses crystal moves, validates the item and hero, uses worn slots 1–3, polls up to
    12 x 0.25 s for landing, and returns NO_EFFECT if the item does not land.
  - `buy_xp` returns the observed levels and coins.
  - `unequip` requires `confirm_bond_loss` for crystals.
  - Equip and unequip hints updated.
- `gear.py` (new): `ITEM_SLOTS = (1, 2, 3)`, with the crystal slot shown as 4.
- `tools.py`: equip description and slot schema (1–4), `unequip` gained `confirm_bond_loss`.
- `README.md`: verified-live list and an equipment-slots section.
- `tests/test_fixes.py` (new): 40 regression tests. They pass against the running copy and the repo.
  The last one, `test_nameless_owned_items_are_named_by_id`, was added in this session and is included.

### Not yet verified live

- `sell_hero` works live (verified this session), `unequip` works live (verified), `move_to_bench` works
  live (verified), `move_to_cell` works live (verified), `equip` works live (verified for several cases).
- `lock_shop`, `swap_bench`, `equip_best`, `auction_bid`, `auction_fixed` and `wait_for` end-to-end
  were not exercised live in a full match.

## 5. Known issues (open)

1. **Equip readback lag:** `equip` can return NO_EFFECT while the item actually landed (the readback took
   longer than 3 s). The `legal` list (crystal_select appearing) is a more reliable signal. Consider
   checking `observe` before retrying.
2. **Choice crystal moves between heroes:** equipping a Choice crystal to a second hero moves it off the
   first hero and drops that hero's bond. Guidance: avoid it, or re-check bonds after.
3. **Level-up NO_EFFECT:** `buy_xp` returned NO_EFFECT at level 4 with 5 gold, with the state unchanged.
   Cause not found. Possible causes: a stale rev, the wrong target, or the level-up gated on a state
   we did not read.
4. **Pick and prompt timing:** item picks and Go Go picks can be refused during a fight and succeed in
   prep. A prompt can also be stale when the round changes. Design the caller to resolve prompts first.
5. **Board list lag:** `observe`'s board can omit a unit for a few seconds. Re-observe before acting.
6. **Bridge drops:** the bridge dropped with WinError 10054 (connection reset) and then WinError 10061
   (refused). `/mcp` reconnect restored it each time. The game kept running in the first drop; it was
   not confirmed in the second. Treat a drop as "stop and report", not "retry in a loop".
7. **Party partner warning:** queueing with a partner on an unstable network was accepted; the match
   ran with that partner present.
8. **Edith's Defender count:** knowledge.py lists Edith as Defender, but an earlier observed Defender
   count did not match a simple count. Unresolved.

## 6. Git

- Repo: `C:\Users\satya\Downloads\mcgg-mcp`, origin `https://github.com/Zeli12345/mcgg-mcp.git`.
- Before this handoff, `main` had one commit (`86e4e86 Initial commit`), and the working tree had
  modified files and untracked new modules.
- This handoff was committed to a feature branch (not `main`), then pushed. See the final message for
  the branch name and commit hash.
- Scratch files in the running copy (`tools/fix_dup.py`, `patch_gogo.py`, `patch_gogo2.py`,
  `patch_observe.py`) were intentionally not committed.

## 7. Next steps, in order

1. Run `/mcp` to reconnect mcgg. Check whether the match is still running. Use `observe` first and
   re-observe before every action.
2. If seated, resolve pending prompts first (`pick_item`, `crystal_select`, `gogo_select`), then shop.
3. Pick Marksman for the Choice crystal on Granger if the prompt is still open.
4. Place Tigreal (Defender) and buy toward 3 Defenders and 3 Marksmen. Prefer 3–5 cost copies.
5. Spend gold above 50 every prep. Roll for copies from round 8 onward.
6. Do not use `equip_best` or `auto_deploy`. Equip by hand and verify with observe.
7. Log one line per round in the match notes: round, gold before and after, buys, sells, equips, result.
