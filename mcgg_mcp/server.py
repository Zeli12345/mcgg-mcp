"""MCP server (stdio JSON-RPC 2.0). No dependencies.

Local, single-operator game-state observer for a running Magic Chess: Go Go client.
It talks only to 127.0.0.1:8787 — a bridge inside the operator's own game process —
reads the client's own managed state, and invokes the same methods the game's UI
invokes when a player clicks. No traffic is intercepted, forged, or redirected; no
other client is accessed; no game files are redistributed.

    python run.py [--base http://127.0.0.1:8787] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback

import tools as T
from bridge import Bridge, BridgeError
from guard import Engine
from observe import Observer, legal_actions

PROTOCOL = '2024-11-05'
POLL = 0.25
# actions that only make sense while the shop is open (prep / forecast / welfare)
SHOP_TOOLS = frozenset({'buy_hero', 'buy_xp', 'reroll_shop', 'lock_shop', 'auto_deploy',
                        'move_to_cell', 'move_to_bench', 'swap_bench', 'equip', 'equip_best',
                        'unequip'})


def dumps(obj) -> str:
    """Compact JSON: no indentation or padding (fewer tokens per reply)."""
    return json.dumps(obj, separators=(',', ':'), default=str)

ABOUT = (
    'Local, single-operator game-state observer for a running Magic Chess: Go Go client. '
    'Connects only to 127.0.0.1:8787, a bridge inside the operator\'s own game process; '
    'reads the client\'s own managed state and invokes the same methods the game UI '
    'invokes. No network interception, no cross-client access, no redistribution.'
)

INSTRUCTIONS = ABOUT + (
    ' Intended for the operator\'s own matches on their own account. Every mutation is '
    'checked against the game\'s live rules (illegal actions return NOT_LEGAL with the '
    'current legal list) and verified afterwards (NO_EFFECT instead of a false success). '
    'Call observe() first and again after each action. Whether the game\'s Terms of '
    'Service permit client modifications is the operator\'s decision; this server makes '
    'no claim of vendor authorization.'
)


class Server:
    def __init__(self, base: str, dry_run: bool = False):
        self.b = Bridge(base)
        self.o = Observer(self.b)
        self.engine = Engine(self.b, self.o, dry_run=dry_run)

    # ---- tool implementations ----------------------------------------
    def call_tool(self, name: str, args: dict) -> dict:
        if name == 'observe':
            payload = self.o.build(
                sections=args.get('sections'),
                detail=args.get('detail', 'summary'),
                fmt=args.get('format', 'json'),
                include_players=bool(args.get('include_players')),
                since_rev=args.get('since_rev'))
            return {'ok': True, 'observation': payload}

        if name == 'help':
            return {'ok': True, 'about': ABOUT, 'protocol': PROTOCOL,
                    'tools': T.TOOLS, 'error_codes': T.ERROR_CODES,
                    'examples': T.EXAMPLES,
                    'observe_schema': {
                        'format': ['json', 'text'], 'detail': ['summary', 'full'],
                        'sections': T.SECTIONS,
                        'notes': 'legal[] is authoritative for the current state; '
                                 'since_rev returns {unchanged:true} when nothing moved'}}

        if name == 'wait_for':
            return self.wait_for(args)

        if name == 'batch':
            return self.batch(args)

        res = self.engine.run(name, args)
        if res.get('ok'):
            res['observation'] = self.o.build(detail='summary', fmt='json')
        return res

    def batch(self, args: dict) -> dict:
        """Run an ordered list of actions in one call.

        The first step is checked against `expect_rev` (the rev of the observation the plan
        was made from). Each later step is checked against the rev the previous step left
        behind, so the whole plan still fails closed if the match moves underneath it.
        Stops at the first failure unless stop_on_error is false. Returns every step's
        result and one final observation.
        """
        steps = args.get('steps') or []
        if not steps:
            return {'ok': False, 'error': {'code': 'BAD_ARGUMENT', 'message': 'steps is empty',
                                           'hint': 'pass steps:[{tool,args}]', 'legal': []}}
        stop = bool(args.get('stop_on_error', True))
        rev = args.get('expect_rev')
        shopping0 = self.o.load().shopping
        out = []
        for i, st in enumerate(steps):
            tool = st.get('tool') or ''
            targs = dict(st.get('args') or {})
            if tool in ('batch', 'observe', 'wait_for', 'help'):
                out.append({'step': i, 'tool': tool, 'ok': False,
                            'error': {'code': 'BAD_ARGUMENT',
                                      'message': f'{tool} cannot be used inside batch'}})
                break
            # the shop closes when the prep phase ends; stop instead of buying into combat
            if shopping0 and tool in SHOP_TOOLS and not self.o.load().shopping:
                out.append({'step': i, 'tool': tool, 'ok': False,
                            'error': {'code': 'PHASE_CHANGED',
                                      'message': 'the shop closed; the rest of the batch was not run',
                                      'hint': "wait_for(phase='GamePhasePrepare')", 'legal': []}})
                break
            if rev is not None and 'expect_rev' not in targs:
                targs['expect_rev'] = rev
            res = self.engine.run(tool, targs)
            out.append({'step': i, 'tool': tool, 'ok': bool(res.get('ok')),
                        'result': res.get('result'), 'error': res.get('error')})
            if not res.get('ok'):
                if stop:
                    break
                continue
            rev = res.get('rev', rev)
        done = len([o for o in out if o['ok']])
        return {'ok': done == len(steps), 'completed': done, 'requested': len(steps),
                'steps': out, 'rev': rev,
                'observation': self.o.build(detail='summary', fmt='json')}

    def wait_for(self, args: dict) -> dict:
        timeout = int(args.get('timeout_s', 120))
        end = time.time() + timeout
        want_phase = args.get('phase')
        want_seated = args.get('seated')
        want_in_match = args.get('in_match')
        left_le = args.get('left_ms_le')
        want_offer = args.get('offer_available')
        want_welfare_turn = args.get('welfare_turn')
        want_altar_free = args.get('altar_free')
        want_altar_turn = args.get('altar_turn')
        want_crystal = args.get('crystal_available')
        want_gogo = args.get('gogo_available')

        while time.time() < end:
            m = self.o.load()
            ok = True
            if want_in_match is not None:
                ok &= (m.in_match == want_in_match)
            if want_seated is not None:
                ok &= (m.seated == want_seated)
            if want_phase is not None:
                ok &= (m.phase == want_phase)
            if want_offer is not None:
                ok &= (bool(m.offers) == want_offer)
            if want_welfare_turn is not None:
                ok &= (bool(self.o.welfare_state().get('my_turn')) == want_welfare_turn)
            if want_altar_free is not None:
                ok &= (self.o.altar_state().get('active') != want_altar_free)
            if want_altar_turn is not None:
                ok &= (bool(self.o.altar_state().get('my_turn')) == want_altar_turn)
            if want_crystal is not None:
                ok &= (bool(self.o.crystal_state().get('active')) == bool(want_crystal))
            if want_gogo is not None:
                ok &= (bool(self.o.gogo_state().get('active')) == bool(want_gogo))
            if left_le is not None:
                t = self.o.timers().get('left_ms')
                ok &= (t is not None and t <= left_le)
            if ok:
                return {'ok': True, 'waited_s': round(timeout - (end - time.time()), 2),
                        'observation': self.o.build(detail='summary', fmt='json')}
            time.sleep(POLL)

        obs = self.o.build(detail='summary', fmt='json')
        return {'ok': False, 'timed_out': True, 'observation': obs,
                'error': {'code': 'TIMEOUT',
                          'message': f'condition not met in {timeout}s',
                          'hint': 'the observation shows the current state; adjust or retry',
                          'legal': legal_actions(self.o.load())}}

    # ---- JSON-RPC -----------------------------------------------------
    def handle(self, msg: dict) -> dict | None:
        method = msg.get('method')
        mid = msg.get('id')

        def ok(result):
            return {'jsonrpc': '2.0', 'id': mid, 'result': result}

        def err(code, message):
            return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': code, 'message': message}}

        if method == 'initialize':
            return ok({'protocolVersion': PROTOCOL,
                       'capabilities': {'tools': {}},
                       'serverInfo': {'name': 'mcgg', 'version': '1.0.0'},
                       'instructions': INSTRUCTIONS})
        if method in ('notifications/initialized', 'initialized'):
            return None
        if method == 'ping':
            return ok({})
        if method == 'tools/list':
            return ok({'tools': T.TOOLS})
        if method == 'tools/call':
            p = msg.get('params') or {}
            name, args = p.get('name') or '', p.get('arguments') or {}
            if name not in {t['name'] for t in T.TOOLS}:
                return ok({'content': [{'type': 'text', 'text': json.dumps(
                    {'ok': False, 'error': {'code': 'UNKNOWN_TOOL', 'message': name,
                                            'hint': 'call help', 'legal': []}})}],
                    'isError': True})
            try:
                result = self.call_tool(name, args)
            except BridgeError as e:
                result = {'ok': False, 'error': {'code': 'BRIDGE_ERROR', 'message': str(e),
                                                 'hint': 'is the game running with BepInEx?',
                                                 'legal': []}}
            except Exception as e:                  # noqa: BLE001
                traceback.print_exc(file=sys.stderr)
                result = {'ok': False, 'error': {'code': 'INTERNAL',
                                                 'message': f'{type(e).__name__}: {e}',
                                                 'hint': 'report this', 'legal': []}}
            return ok({'content': [{'type': 'text', 'text': dumps(result)}],
                       'isError': not result.get('ok', False)})
        if method == 'resources/list':
            return ok({'resources': [{'uri': 'mcgg://state', 'name': 'Match state',
                                      'mimeType': 'application/json'}]})
        if method == 'resources/read':
            return ok({'contents': [{'uri': 'mcgg://state', 'mimeType': 'application/json',
                                     'text': json.dumps(self.o.build(detail='full'), default=str)}]})
        return err(-32601, f'method not found: {method}')

    def serve(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.handle(msg)
            if resp is None:
                continue
            sys.stdout.write(dumps(resp) + '\n')
            sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8787')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    Server(a.base, a.dry_run).serve()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())