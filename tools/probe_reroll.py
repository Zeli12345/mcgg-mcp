import json, time, urllib.parse, urllib.request

B = 'http://127.0.0.1:8787'
LBM = 'MCLogicBattleData.battleManager'


def get(p):
    return json.load(urllib.request.urlopen(B + p, timeout=20))


def call(path, method, *args):
    q = 'path=%s&method=%s&args=%s' % (urllib.parse.quote(path, safe=''), method,
                                       ','.join(str(a) for a in args))
    return get('/call?' + q)


def gogo():
    return (get('/match') or {}).get('gogo')


print('before:', gogo())
if gogo() and gogo().get('status') == 'CanSelect':
    for path in (LBM + '.m_GoGoCardComp', LBM + '.m_GoGoCardComp.m_PaidDiceComp'):
        r = call(path, 'ReRandomCard', 1, 1)
        time.sleep(0.8)
        after = gogo()
        print('%-46s -> %s' % (path.split('battleManager.')[-1], json.dumps(r)[:90]))
        print('   after:', after)
        if after and after.get('remaining') != gogo().get('remaining'):
            break
else:
    print('prompt not open')
