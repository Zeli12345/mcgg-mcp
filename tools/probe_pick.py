import json, urllib.parse, urllib.request

B = 'http://127.0.0.1:8787'


def get(p):
    return json.load(urllib.request.urlopen(B + p, timeout=25))


def call(path, method, *args):
    q = 'path=%s&method=%s&args=%s' % (urllib.parse.quote(path, safe=''), method,
                                       ','.join(str(a) for a in args))
    return get('/call?' + q)


def offers():
    m = get('/match')
    return [(o.get('guid'), o.get('dropGuid')) for o in (m.get('offers') or [])]


print('offers before:', offers())
try:
    print('pick by dropGuid:', call('MCLogicBattleData.battleManager.m_ChessPick',
                                    'OnPickDistributeRes', *offers()[0][::-1]))
except Exception as e:
    print('err', e)
print('offers after :', offers())
