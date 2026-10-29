"""HTTP transport for the in-game MCGG bridge (BepInEx plugin on 127.0.0.1:8787).

Scope: loopback only. The bridge listens on 127.0.0.1 inside the operator's own game
process; this transport never contacts a remote host and carries no third-party data.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class BridgeError(RuntimeError):
    pass


class Bridge:
    def __init__(self, base: str = 'http://127.0.0.1:8787', timeout: float = 25.0):
        self.base = base.rstrip('/')
        self.timeout = timeout

    def _get(self, endpoint: str, **params) -> dict:
        url = self.base + endpoint
        if params:
            url += '?' + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or '{}')
        except urllib.error.URLError as e:
            raise BridgeError(f'bridge unreachable: {e}') from e
        except json.JSONDecodeError as e:
            raise BridgeError(f'bad json from {endpoint}: {e}') from e

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(
            self.base + '/act', data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or '{}')
        except urllib.error.URLError as e:
            raise BridgeError(f'bridge unreachable: {e}') from e

    # ---- reads --------------------------------------------------------
    def match(self) -> dict:
        return self._get('/match')

    def probe(self, path: str) -> dict:
        return self._get('/probe', path=path)

    def call(self, path: str, method: str, *args) -> dict:
        return self._get('/call', path=path, method=method,
                         args=','.join(str(a) for a in args) if args else None)

    def cfg(self, kind: str, ident: int, upg: int = 0) -> dict:
        return self._get('/cfg', kind=kind, id=ident, upg=upg)

    def price(self) -> dict:
        return self._get('/price')

    def selftest(self) -> dict:
        return self._get('/selftest')

    def ping(self) -> dict:
        return self._get('/ping')

    # ---- writes -------------------------------------------------------
    def act(self, **payload) -> dict:
        return self._post(payload)

    def buy(self, slot: int) -> dict:
        return self.act(op='buy', index=slot)

    def refresh(self) -> dict:
        return self.act(op='refresh')

    def deploy(self) -> dict:
        return self.act(op='deploy')

    def equip(self, item_guid: int, hero_guid: int, slot: int = 1) -> dict:
        return self.act(op='equip', equip=item_guid, hero=hero_guid, slot=slot)