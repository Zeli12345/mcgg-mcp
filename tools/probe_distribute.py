import json, time, urllib.request

B = 'http://127.0.0.1:8787'


def get(p):
    return json.load(urllib.request.urlopen(B + p, timeout=25))


def act(payload):
    r = urllib.request.Request(B + '/act', data=json.dumps(payload).encode(),
                               headers={'Content-Type': 'application/json'}, method='POST')
    return json.load(urllib.request.urlopen(r, timeout=30))


def offers():
    m = get('/match')
    return [(o.get('guid'), [ (i.get('raw') or {}).get('m_iItemParam1') for i in (o.get('items') or []) ])
            for o in (m.get('offers') or [])]


print('offers before:', offers())

attempts = [
    ('TryDistributeMagicCrystal', [0]),
    ('TryDistributeMagicCrystal', [1]),
    ('TryDistributeMagicCrystal', [2]),
    ('TryDistributeSuperCrystal', []),
    ('TryEquipDistribute', [0]),
    ('TryEquipDistribute', [1]),
    ('TryAutoDistributeEquip', []),
    ('TryAutoDistributeEquipmentByWeight', [1, 1, 1, 1, 0]),
]

for method, args in attempts:
    before = offers()
    if not before:
        print('queue empty'); break
    res = act({'op': 'api', 'method': method, 'args': args})
    time.sleep(0.8)
    after = offers()
    drained = len(after) < len(before)
    print('%-38s %s -> %s  drained=%s  before=%d after=%d'
          % (method + str(args), json.dumps(res)[:70], '', drained, len(before), len(after)))
    if drained:
        print('   winner:', method, args, 'offers now', after)
        break
