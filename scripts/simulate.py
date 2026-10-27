"""Drive a running API with SYNTHETIC events for demos. Prints counts only; this is not an experiment.

    python scripts/simulate.py --url http://localhost:8000 --n 60
"""

from __future__ import annotations

import argparse
import json
import urllib.request


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    print(post(f"{a.url}/api/demo/seed", {"n": a.n, "seed": a.seed}))
    with urllib.request.urlopen(f"{a.url}/api/memory/stats") as r:
        print(json.loads(r.read()))


if __name__ == "__main__":
    main()
