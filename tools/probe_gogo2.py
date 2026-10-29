import json, time, urllib.parse, urllib.request
B='http://127.0.0.1:8787'
LBM='MCLogicBattleData.battleManager'
DICE=LBM+'.m_GoGoCardComp.m_PaidDiceComp'
DATA=LBM+'.m_GoGoCardComp.m_CurrData'
def get(p): return json.load(urllib.request.urlopen(B+p,timeout=25))
def call(path,method,*a):
    q='path=%s&method=%s&args=%s'%(urllib.parse.quote(path,safe=''),method,','.join(str(x) for x in a))
    return get('/call?'+q)
def st():
    d=(get('/probe?path='+urllib.parse.quote(DATA,safe='')) or {}).get('members') or {}
    return {k:d.get(k) for k in ('m_Status','iRemainCount','m_CardId','m_iIndex','m_Quality')}
print('before', st())
for idx in (0,1):
    r=call(DICE,'OnReRandomCard',idx,1)
    time.sleep(1)
    print('idx',idx,'->',json.dumps(r)[:90],'|',st())
