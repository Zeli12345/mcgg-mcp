"""Watch the GoGo prompt and log every state transition.

    python tools/gogo_watch.py --seconds 900

Writes one JSON line per change to gogo_watch.jsonl:
  t, status, remaining, cards[], raw
"""
import argparse
import json
import time
import urllib.request
from datetime import datetime

B = 'http://127.0.0.1:8787'


def gogo():
    try:
        m = json.load(urllib.request.urlopen(B + '/match', timeout=10))
    except Exception:
        return None
    return (m or {}).get('gogo')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=int, default=900)
    ap.add_argument('--interval', type=float, default=0.7)
    ap.add_argument('--out', default='gogo_watch.jsonl')
    args = ap.parse_args()

    prev = '\0'
    end = time.time() + args.seconds
    with open(args.out, 'a', encoding='utf-8') as fh:
        while time.time() < end:
            g = gogo()
            key = json.dumps(g, sort_keys=True, default=str)
            if key != prev:
                rec = {'t': datetime.now().strftime('%H:%M:%S.%f')[:-3], 'gogo': g}
                fh.write(json.dumps(rec, default=str) + '\n')
                fh.flush()
                prev = key
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
