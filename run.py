#!/usr/bin/env python3
"""Update everything: fetch data, simulate, build the page.

  python3 run.py              # fetch from backgammon.dk, simulate, build
  python3 run.py --offline    # reuse the saved raw pages in data/raw/
  python3 run.py -n 20000     # fewer simulations (quicker test)
  python3 run.py --build-only # only rebuild the page from data/results.json
  python3 run.py --if-changed # stop (printing NO_NEW_DATA) unless results or
                              # announced lineups changed since the last run
"""

import argparse
import json
import sys
import time

from bgsim import build, config, scrape, simulate


def fingerprint(season: dict) -> str:
    """What counts as new data: match results and announced lineups."""
    keys = ("date", "home", "away", "played", "home_ekv", "away_ekv", "lineup")
    rows = [{k: m.get(k) for k in keys} for m in season["matches"]]
    return json.dumps(rows, sort_keys=True, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--if-changed", action="store_true")
    ap.add_argument("-n", "--sims", type=int, default=config.N_SIMULATIONS)
    args = ap.parse_args()

    if not args.build_only:
        t0 = time.time()
        old_text = (scrape.SEASON_JSON.read_text(encoding="utf-8")
                    if scrape.SEASON_JSON.exists() else None)
        season = scrape.scrape(offline=args.offline)
        if args.if_changed and old_text and fingerprint(json.loads(old_text)) == fingerprint(season):
            scrape.SEASON_JSON.write_text(old_text, encoding="utf-8")  # keep the tree clean
            print("NO_NEW_DATA: no new results or lineups since the last run")
            return 0
        played = sum(m["played"] for m in season["matches"])
        print(f"Data: {len(season['teams'])} teams, {played}/{len(season['matches'])} matches played "
              f"({time.time() - t0:.1f} s)")
        lineups = [m for m in season["matches"] if "lineup" in m]
        if lineups:
            print(f"  {len(lineups)} unplayed matches with an announced lineup")

        t0 = time.time()
        results = simulate.run(season, n_sims=args.sims)
        simulate.RESULTS_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        simulate.update_history(results)
        print(f"Simulation: {args.sims} runs ({time.time() - t0:.1f} s)")
        print(f"{'Team':26s} {'Rating':>7s} {'Title':>7s} {'F4':>7s} {'Releg':>7s}")
        for t in sorted(results["teams"], key=lambda t: -t["p_title"]):
            print(f"{t['name']:26s} {t['strength']:7.1f} {t['p_title']:7.1%} "
                  f"{t['p_final4']:7.1%} {t['p_relegated']:7.1%}")

    build.build()
    print("Built docs/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
