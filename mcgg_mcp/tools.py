"""Tool definitions (JSON Schema) + dispatch table.

Scope: tools for observing and playing the operator's own Magic Chess: Go Go client.
Each tool maps to a game method the UI itself calls; none of them touch other clients,
network traffic, or files outside this machine.

Every schema is strict: additionalProperties:false, enums where a value is constrained,
min/max on every bounded number, and a description that says *when* to use the tool and
which observe() field to read first.
"""
from __future__ import annotations

PHASES = ['GamePhasePrepare', 'GamePhaseForecast', 'GamePhaseWelfare',
          'GamePhaseFight', 'GamePhaseFightCountDown', 'GamePhaseFightResult']

SECTIONS = ['meta', 'economy', 'shop', 'bench', 'board', 'items', 'pending',
            'timers', 'legality', 'bonds', 'players']


def tool(name, title, desc, props=None, required=None, annotations=None):
    return {
        'name': name,
        'title': title,
        'description': desc,
        'inputSchema': {'type': 'object', 'additionalProperties': False,
                        'properties': props or {}, 'required': required or []},
        'annotations': annotations or {},
    }


TOOLS = [
    tool('observe', 'Read match state',
         'Match state: round, economy, shop, bench, board, items, pending prompts, timers, '
         'legal actions. Call first and after every action. since_rev=<last rev> returns '
         '{unchanged:true} when nothing moved.',
         {'format': {'type': 'string', 'enum': ['json', 'text'], 'default': 'json',
                     'description': 'json for tooling, text for compact reading'},
          'detail': {'type': 'string', 'enum': ['summary', 'full'], 'default': 'summary'},
          'sections': {'type': 'array', 'items': {'type': 'string', 'enum': SECTIONS},
                       'description': 'restrict to these sections; default all core sections'},
          'include_players': {'type': 'boolean', 'default': False},
          'since_rev': {'type': 'integer', 'description': 'rev from a previous observe'}},
         annotations={'readOnlyHint': True}),

    tool('batch', 'Run several actions in one call',
         'Ordered actions in one call (prep window). expect_rev = rev from observe. Stops at '
         'the first failure, or when the shop closes (PHASE_CHANGED). Returns step results '
         'and one observation. observe/wait_for/help cannot be batched.',
         {'steps': {'type': 'array', 'minItems': 1, 'maxItems': 12,
                    'items': {'type': 'object', 'additionalProperties': False,
                              'properties': {'tool': {'type': 'string'},
                                             'args': {'type': 'object'}},
                              'required': ['tool']}},
          'stop_on_error': {'type': 'boolean', 'default': True}},
         ['steps']),

    tool('wait_for', 'Wait until a condition',
         'Block until the match reaches a state, then return a fresh observation. '
         'Use instead of polling. Common: phase=GamePhasePrepare, seated=true, '
         'left_ms<=2000, offer_available=true, altar_free=true, altar_turn=true.',
         {'phase': {'type': 'string', 'enum': PHASES},
          'seated': {'type': 'boolean'},
          'left_ms_le': {'type': 'integer', 'minimum': 0},
          'offer_available': {'type': 'boolean'},
          'welfare_turn': {'type': 'boolean', 'description': 'true = it is your turn to choose a welfare reward'},
          'altar_free': {'type': 'boolean',
                         'description': 'true = the 8-player altar selection is not running'},
          'altar_turn': {'type': 'boolean',
                         'description': 'true = it is your turn to choose in the altar'},
          'crystal_available': {'type': 'boolean', 'description': 'true = crystal choice is open'},
          'gogo_available': {'type': 'boolean', 'description': 'true = GoGo card choice is open'},
          'in_match': {'type': 'boolean'},
          'timeout_s': {'type': 'integer', 'minimum': 1, 'maximum': 600, 'default': 120}},
         annotations={'readOnlyHint': True}),

    tool('help', 'Tool catalog and schemas',
         'Return every tool, the observe schema, error codes and examples.',
         annotations={'readOnlyHint': True}),

    tool('buy_hero', 'Buy a shop hero',
         'Buy the hero in shop slot N. Needs coin >= cost. Read observe().shop.slots first; '
         '"makes":"2*" marks the purchase that completes a two-star.',
         {'slot': {'type': 'integer', 'minimum': 0, 'maximum': 4}},
         ['slot'], {'destructiveHint': True}),

    tool('sell_hero', 'Sell a hero',
         'Sell a board or bench hero for gold (verified in prepare; the sale refunds the '
         'hero price). bench_slot resolves to the unit guid before selling. Not during the altar phase.',
         {'hero_guid': {'type': 'integer', 'description': 'unit guid from observe()'},
          'bench_slot': {'type': 'integer', 'minimum': 1, 'maximum': 9, 'description': 'alternative to hero_guid'}},
         annotations={'destructiveHint': True}),

    tool('reroll_shop', 'Reroll the shop',
         'Spend gold to reroll the shop. Needs coin >= shop.refresh_cost.',
         annotations={'destructiveHint': True}),

    tool('buy_xp', 'Level up (buy experience)',
         'Spend gold to reach the next player level. Needs coin >= me.level_price. '
         'Leveling raises the shop tier and board capacity.',
         annotations={'destructiveHint': True}),

        tool('lock_shop', 'Lock or unlock the shop',
         'Freeze the current shop so it is not rerolled automatically.',
         {'locked': {'type': 'boolean', 'default': True}},
         annotations={'idempotentHint': True}),

    tool('move_to_cell', 'Move hero to a board cell',
         'Place a hero on (x,y) of the 7x6 board. Works for a board hero (moves it) and a bench '
         'hero (deploys it). Shopping phases only; returns HERO_SLOTS_FULL when the board '
         'has no room, and NO_EFFECT when the cell is occupied.',
         {'hero_guid': {'type': 'integer'},
          'x': {'type': 'integer', 'minimum': 0, 'maximum': 6},
          'y': {'type': 'integer', 'minimum': 0, 'maximum': 5}},
         ['hero_guid', 'x', 'y']),

    tool('move_to_bench', 'Move hero to bench',
         'Send a BOARD hero back to a bench slot (verified). Shopping phases only.',
         {'hero_guid': {'type': 'integer'},
          'slot': {'type': 'integer', 'minimum': 1, 'maximum': 9,
                   'description': 'bench slot; omitted = the lowest free slot'}},
         ['hero_guid']),

    tool('swap_bench', 'Swap two bench slots',
         'Move or exchange bench heroes between two slots (verified). Shopping phases only.',
         {'from_slot': {'type': 'integer', 'minimum': 1, 'maximum': 9},
          'to_slot': {'type': 'integer', 'minimum': 1, 'maximum': 9}},
         ['from_slot', 'to_slot']),

    tool('auto_deploy', 'Auto-arrange the board',
         'Let the game place your units. Shopping phases only.',
         annotations={'idempotentHint': True}),

    tool('equip', 'Equip an item or crystal on a hero',
         'Slots: 1 = special slot (only place a Choice Magic Crystal can go), 2-4 = item slots. '
         'Equipping the crystal into slot 1 opens its three bond options, which crystal_select then commits.',
         {'item_guid': {'type': 'integer'},
          'hero_guid': {'type': 'integer'},
          'slot': {'type': 'integer', 'minimum': 1, 'maximum': 4, 'default': 1,
                   'description': '1 = special (crystal), 2-4 = normal item slots'}},
         ['item_guid', 'hero_guid'], {'idempotentHint': True}),

    tool('equip_best', 'Equip every bag item on the carry',
         'Distribute all free items onto the strongest hero (highest star then quality).',
         annotations={'idempotentHint': True}),

    tool('unequip', 'Return an item to the bag',
         'Return an equipped item to the bag (verified). Shopping phases only.',
         {'item_guid': {'type': 'integer'}}, ['item_guid'],
         {'destructiveHint': True}),

    tool('pick_item', 'Resolve a pending item offer',
         'Choose one option from the blocking pick prompt. All offers must be resolved '
         'before the bag and shop reopen.',
         {'offer_guid': {'type': 'integer'},
          'index': {'type': 'integer', 'minimum': 0, 'default': 0}},
         ['offer_guid']),

    tool('welfare_pick', 'Choose a reward in the welfare selection',
         'Take a reward card during your turn in the Welfare selection (after creep rounds). '
         'The tool waits for your turn (wait_s) and clicks the card on screen the moment it '
         'opens, then checks the Selected state. card optionally picks a specific card; by '
         'default the cards are tried in order until one is accepted. Refused with '
         'WELFARE_LOCKED when it is not your turn.',
         {'card': {'type': 'string', 'enum': ['top_left', 'top', 'top_right', 'top_mid_right',
                                              'left', 'mid_left', 'mid_right', 'right'],
                   'description': 'preferred card position on the ring'},
          'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 120, 'default': 25,
                     'description': 'seconds to wait for your turn before giving up'}},
         []),

    tool('crystal_select', 'Choose a magic crystal bond option',
         'Pick one of the offered crystal options.',
         {'index': {'type': 'integer', 'minimum': 0}}, ['index']),

    tool('gogo_reroll', 'Reroll one GoGo card choice',
         'Replace one of the two offered GoGo cards. Needs remaining rerolls; '
         'observe().pending.gogo.remaining_rerolls shows how many are left.',
         {'index': {'type': 'integer', 'minimum': 0, 'maximum': 1, 'default': 0}},
         annotations={'destructiveHint': True}),

    tool('gogo_select', 'Select a GoGo / commander card',
         'Take a card from the current prompt. index 0 = the first card, 1 = the second '
         '(see observe().pending.gogo.cards). When index is omitted, the game auto-picks '
         'using mode (0 default).',
         {'index': {'type': 'integer', 'minimum': 0, 'maximum': 1},
          'mode': {'type': 'integer', 'minimum': 0, 'default': 0}}),
]

ERROR_CODES = {
    'NOT_SEATED': 'not in a match, or the client is mid-transition',
    'PHASE_LOCKED': 'this action needs a shopping phase (board is frozen during combat)',
    'ALTAR_ACTIVE': 'the 8-player altar selection is running; wait for wait_for(altar_free=true)',
    'NOT_LEGAL': 'not valid for the current state; read observe().legal',
    'RATE_LIMIT': 'too many actions this minute',
    'BAD_ARGUMENT': 'missing or invalid argument',
    'BRIDGE_ERROR': 'the game bridge did not answer',
    'INTERNAL': 'unexpected failure',
    'TIMEOUT': 'wait_for reached its deadline without the condition holding',
    'STALE_REV': 'the match changed since the observation you acted on; observe again',
    'NO_EFFECT': 'the game accepted the call but the state did not change',
    'WELFARE_LOCKED': 'the welfare reward is not your turn yet; wait_for(welfare_turn=true)',
    'PICK_PENDING': 'an item offer is waiting; resolve it with pick_item first',
    'HERO_SLOTS_FULL': 'the board has no free slot (Hero Slots are full); sell, bench or level up',
    'GAME_REJECTED': 'the game refused the action; see result for the reason',
    'UNKNOWN_TOOL': 'no such tool; call help',
}

EXAMPLES = [
    {'call': 'observe', 'args': {}},
    {'call': 'observe', 'args': {'format': 'text'}},
    {'call': 'buy_hero', 'args': {'slot': 2}, 'why': 'slot 2 shows "makes":"2*"'},
    {'call': 'move_to_cell', 'args': {'hero_guid': 38, 'x': 3, 'y': 2}},
    {'call': 'wait_for', 'args': {'phase': 'GamePhasePrepare'}},
    {'call': 'wait_for', 'args': {'altar_turn': True, 'timeout_s': 120}},
]
# every mutating tool accepts the rev of the observation it was planned from
_REV = {'type': 'integer',
        'description': 'rev from observe(); the call fails with STALE_REV if the match moved on'}
for _t in TOOLS:
    if _t['name'] not in ('observe', 'wait_for', 'help'):
        _t['inputSchema']['properties']['expect_rev'] = _REV
