# mcgg-mcp

A local MCP server for a single running **Magic Chess: Go Go** client.

It exposes the client's own match state as structured tools and lets an agent perform the
same actions a player performs in the game's UI: buying, selling, rerolling, placing units,
equipping items, and choosing rewards and commander cards.

## Scope

- **Local only.** The server talks to `127.0.0.1:8787`, a bridge loaded into the operator's
  own game process. There is no remote endpoint and no third-party data.
- **Same methods as the UI.** Each action maps to a game method the UI itself calls
  (`BuyHero`, `ReRandomCard`, `OnSelectBond`, `OnPickDistributeRes`, and others). The game's
  own rules and validations apply.
- **No interception.** Nothing reads, forges or redirects network traffic, no other
  player's client is accessed, and no game files are redistributed.
- **Bounded.** Mutations are checked against the live legal-action list, rate-limited to
  30 per minute (prompt answers are exempt), optionally dry-run, and verified afterwards
  (`NO_EFFECT` instead of a false success). Every action accepts `expect_rev` and fails with
  `STALE_REV` if the match has moved on.

Intended use is the operator's own matches on their own account. Whether the game's Terms of
Service permit client modifications is the operator's decision. This project makes no claim
of vendor authorization.

## Tools (21)

| Tool | Purpose |
|---|---|
| `observe` | Full match state: round, phase, economy, shop, bench, board, items, pending prompts, bonds, timers, legal actions |
| `wait_for` | Block until a condition (phase, seat, countdown, prompt, welfare turn, altar turn) holds |
| `batch` | Run up to 12 actions in one call; stops at the first failure or when the shop closes |
| `help` | Tool catalog, observe schema, error codes, examples |
| `buy_hero` / `sell_hero` / `reroll_shop` / `buy_xp` / `lock_shop` | Shop and economy |
| `move_to_cell` / `move_to_bench` / `swap_bench` / `auto_deploy` | Board arrangement |
| `equip` / `equip_best` / `unequip` | Item and crystal placement |
| `pick_item` | Resolve a pending item offer |
| `welfare_pick` | Take a reward card in the welfare selection (clicks the card on screen) |
| `crystal_select` | Choose a magic crystal bond option |
| `gogo_select` / `gogo_reroll` | Commander (GoGo) card choice and reroll |

`gogo_select` takes `index` (0 = first card, 1 = second). Without it, the game's own
auto-picker runs with `mode`.

## observe

- `format: "json"` (default) returns a typed envelope; `format: "text"` returns a compact block.
- `detail: "summary"` returns the essentials; `detail: "full"` adds the board grid, timers and bonds.
- `since_rev` takes the previous `rev` and returns `{unchanged: true}` when nothing moved.

`legal[]` in each response is authoritative for the current state. Every refusal returns
`{code, message, hint, legal}`, so the caller knows what to do instead.

## Run

```powershell
python run.py                 # stdio MCP server
python run.py --dry-run       # validate decisions without sending actions
python tools/smoke.py         # handshake, tool list, observe, and a guard denial
```

No third-party packages are needed. Python 3.11 or later is recommended.

## Client configuration

```json
{
  "mcpServers": {
    "mcgg": {
      "type": "stdio",
      "command": "python",
      "args": ["<path-to>/mcgg-mcp/run.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

## Requirements

The game client must be running with the bridge plugin loaded. If the bridge is not
reachable, tools return `BRIDGE_ERROR` with a hint instead of failing silently.

## Verification status

Status as of the last audit. "Verified" means exercised against a live client. "Unverified"
means the code path exists but no live run is recorded.

| Status | Tools |
|---|---|
| Verified | `observe`, `help`, `buy_xp`, `pick_item`, `crystal_select`, `gogo_select` (picks), `welfare_pick` |
| Partly verified | `move_to_cell` (prep row limit verified; readback gap), `equip` (crystal path only) |
| Suspected broken | `equip_best`: the first item goes to slot 1, the crystal slot (from code reading; needs a live test) |
| Unverified | `move_to_bench`, `swap_bench`, `unequip`, `gogo_reroll`, `lock_shop` |
| Unsure | `wait_for`, `batch`, `buy_hero`, `sell_hero`, `reroll_shop`, `auto_deploy` |

Known open issues:
- `observe.free_refresh_remaining` has not been checked against the on-screen "FREE xN" label.
- `welfare_pick` clicks bypass the winput stop controls.
- `gogo_select` returns `NO_EFFECT` instead of `BAD_ARGUMENT` for an out-of-range index.
- The `equip` hint says slots 1–3; the schema allows 1–4.

## Error codes

`NOT_SEATED`, `PHASE_LOCKED`, `ALTAR_ACTIVE`, `NOT_LEGAL`, `RATE_LIMIT`, `BAD_ARGUMENT`,
`BRIDGE_ERROR`, `INTERNAL`, `TIMEOUT`, `STALE_REV`, `NO_EFFECT`, `GAME_REJECTED`,
`PICK_PENDING`, `HERO_SLOTS_FULL`, `UNKNOWN_TOOL`.
