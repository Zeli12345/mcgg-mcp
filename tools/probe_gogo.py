import json, time, urllib.parse, urllib.request

B = 'http://127.0.0.1:8787'
LBM = 'MCLogicBattleData.battleManager'
DICE = LBM + '.m_GoGoCardComp.m_PaidDiceComp'
DATA = LBM + '.m_GoGoCardComp.m_CurrData'


def get(p):
    return json.load(urllib.request.urlopen(B + p, timeout=25))


def call(path, method, *args):
    q = 'path=%s&method=%s&args=%s' % (urllib.parse.quote(path, safe=''), method,
                                       ','.join(str(a) for a in args))
    return get('/call?' + q)


def state():
    d = (get('/probe?path=' + urllib.parse.quote(DATA, safe='')) or {}).get('members') or {}
    return {k: d.get(k) for k in ('m_Status', 'iRemainCount', 'iRefreshCount', 'iRfReShType',
                                  'iRfreshType', 'm_CardId', 'm_iIndex', 'm_Quality')}


def dice():
    d = (get('/probe?path=' + urllib.parse.quote(DICE, safe='')) or {}).get('members') or {}
    return {k: d.get(k) for k in ('diceNum', 'usedDiamondCount')}


print('before  :', state(), dice())

for idx in (0, 1):
    for typ in (0, 1):
        r = call(DICE, 'OnReRandomCard', idx, typ)
        time.sleep(0.8)
        s = state()
        print('reroll idx=%s type=%s -> %s | %s' % (idx, typ, json.dumps(r)[:80], s))
        if s.get('iRemainCount') != state().get('iRemainCount'):
            break
