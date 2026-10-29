"""Smoke test: handshake, tool list, observe (json + text), guard denial."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(ROOT, 'run.py')


def rpc(p, msg):
    p.stdin.write(json.dumps(msg) + '\n')
    p.stdin.flush()
    return json.loads(p.stdout.readline())


def call(p, name, args, rid):
    r = rpc(p, {'jsonrpc': '2.0', 'id': rid, 'method': 'tools/call',
                'params': {'name': name, 'arguments': args}})
    res = r.get('result') or {}
    txt = (res.get('content') or [{}])[0].get('text', '{}')
    return json.loads(txt)


def main():
    p = subprocess.Popen([sys.executable, RUN], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, bufsize=1)
    init = rpc(p, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
    print('initialize :', init['result']['serverInfo'])

    tl = rpc(p, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})['result']['tools']
    bad = [t['name'] for t in tl if not isinstance(t.get('inputSchema'), dict)]
    print('tools      :', len(tl), 'missing inputSchema:', bad)

    h = call(p, 'help', {}, 3)
    print('help       :', 'tools=%d codes=%d' % (len(h.get('tools', [])), len(h.get('error_codes', {}))))

    o = call(p, 'observe', {}, 4)
    print('observe    :', json.dumps(o.get('observation'))[:200])

    t = call(p, 'observe', {'format': 'text'}, 5)
    txt = (t.get('observation') or {}).get('text', '')
    print('text form  :', txt.replace('\n', ' | ')[:200])

    d = call(p, 'buy_hero', {'slot': 9}, 6)
    print('denial     :', json.dumps(d.get('error'))[:220])

    p.terminate()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())