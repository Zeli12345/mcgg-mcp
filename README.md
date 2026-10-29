# mcgg-mcp

A local MCP server for a single running **Magic Chess: Go Go** client.

It exposes the client's own match state as structured tools and lets an agent perform the
same actions a player performs in the game's UI — buying, selling, rerolling, placing
units, equipping items, choosing rewards and commander cards.

## Scope

- **Local.** The server talks only to `127.0.0.1:8787`, a bridge loaded into the operator's
  own game process. There is no remote endpoint and no third-party data.
- **Same methods as the UI.** Every action maps to a game method the UI itself calls
  (`BuyHero`, `ReRandomCard`, `OnSelectBond`, `OnPickDistributeRes`, …). The game's own
  rules and validations apply.
- **No interception.** Nothing reads, forges, or redirects network traffic; no other
  player's client is accessed; no game files are redistributed.
- **Bounded.** Mutations are checked against the live legal-action list, rate-limited to
  30/minute, optionally dry-run, and verified afterwards (`NO_EFFECT` rather than a false
  success). Every action accepts `expect_rev` and fails with `STALE_REV` if the match moved.

Intended use is the operator's own matches on their own account. Whether the game's Terms
of Service permit client modifications is the operator's decision; this project makes no
claim of vendor authorization.

## Tools (21)

| tool | purpose |
|---|---|
| `observe` | full match state: round/phase, economy, shop, bench, board, items, pending prompts, bonds, timers, legal actions |
| `wait_for` | block until a condition (phase, seat, countdown, prompt) instead of polling |
| `help` | catalog, observe schema, error codes, examples |
| `buy_hero` / `sell_hero` / `reroll_shop` / `buy_xp` / `lock_shop` | shop and economy |
| `move_to_cell` / `move_to_bench` / `swap_bench` / `auto_deploy` | board arrangement |
| `equip` / `equip_best` / `unequip` | item and crystal placement |
| `pick_item` | resolve a pending item offer (works in combat too) |
| `auction_bid` / `auction_fixed` | altar auction |
| `crystal_select` | choose a magic crystal bond option |
| `gogo_reroll` / `gogo_select` | commander (GoGo) card reroll and choice |

`gogo_select` takes `index` (0 = first card, 1 = second); without it, the game's own
auto-picker runs with `mode`.

## observe

Two renderings of one model:

- `format:"json"` (default) — typed envelope, readable keys, empty sections omitted
- `format:"text"` — compact aligned block for reading
- `detail:"summary"` — essentials; `detail:"full"` adds the board grid, timers, bonds
- `since_rev` — pass the previous `rev` to get `{unchanged:true}` in a few tokens

`legal[]` in the response is authoritative for the current state; every refusal returns
`{code, message, hint, legal}` so the caller knows what to do instead.

## Run

```powershell
python run.py                      # stdio MCP server
python run.py --dry-run            # validate decisions without sending actions
python tools/smoke.py              # handshake + tool list + observe + denial
```

## Client configuration

```json
{
  "mcpServers": {
    "mcgg": {
      "type": "stdio",
      "command": "python",
      "args": ["C:/Users/satya/Downloads/New folder (53)/mcgg-mcp/run.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

## Requirements

The game client must be running with the bridge plugin loaded. If the bridge is not
reachable, tools return `BRIDGE_ERROR` with a hint rather than failing silently.

## Verification status

Verified live: `observe`, `buy_hero`, `buy_xp`, `auto_deploy`, `pick_item`,
`crystal_select`, `gogo_reroll`, and the `SelectCard` path behind `gogo_select`.

`equip` was live-checked before the readback fix below and needs re-verification: an earlier
version reported success for calls that never moved the item.

## Equipment slots

Observed live: a hero's worn items sit in slots 1 to 3, and a crystal sits in the crystal slot,
which `observe` reports as slot 4. `equip` takes a worn slot (omit it to take the first free
one), refuses a slot the hero already uses, and returns `NO_EFFECT` unless the item lands on
the hero within about 3 s. Crystals are always sent to the crystal slot. A hero that already has
a crystal refuses another one. Removing a crystal drops its bond, so `unequip` needs
`confirm_bond_loss: true` for a crystal.

Not yet exercised against a live client: `sell_hero`, `lock_shop`, `move_to_cell`,
`move_to_bench`, `swap_bench`, `equip_best`, `unequip`, `auction_bid`, `auction_fixed`,
and `wait_for` end-to-end.

## Error codes

`NOT_SEATED`, `PHASE_LOCKED`, `ALTAR_ACTIVE`, `NOT_LEGAL`, `RATE_LIMIT`, `BAD_ARGUMENT`,
`BRIDGE_ERROR`, `INTERNAL`, `TIMEOUT`, `STALE_REV`, `NO_EFFECT`, `GAME_REJECTED`,
`UNKNOWN_TOOL`.
