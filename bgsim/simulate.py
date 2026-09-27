"""Monte Carlo simulation of the rest of Elitedivisionen.

Model
-----
* Team strength = average rating of the players who have played for the team
  so far, weighted by individual games played (K).
* Single-game win probability from the DBgF rating formula:
      P_upset = 1 / (10^(D*sqrt(N)/2000) + 1)
  where D is the rating difference and N = 17 (match length). P_upset is the
  chance that the lower-rated player wins.
* A team match = 4 independent individual games => home EKV ~ Bin(4, p).
  With an announced lineup, each board uses the actual players' ratings.
* 2 MP for a win (3-1, 4-0), 1 MP for 2-2, 0 for a loss (regulations § 5.10).
* Ranking (§ 3.3): 1) EKV, 2) MP, 3) head-to-head, 4) play-off match.
  Head-to-head is read as EKV, then MP, in the matches between the tied
  teams. The play-off match is modelled as a random order.
* The top 4 after the regular season play the final four (each meets the other
  three once; EKV and MP are added to the regular-season totals). The leader
  after the final four is Danish champion (Danmarksmester).
* Places 10-12 after the regular season are relegated directly.
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

from . import config

ROOT = Path(__file__).resolve().parent.parent
RESULTS_JSON = ROOT / "data" / "results.json"
HISTORY_JSON = ROOT / "data" / "history.json"


def game_win_prob(r_a: float, r_b: float, n: int = config.MATCH_LENGTH) -> float:
    """Probability that player A (rating r_a) beats B in an n-point match."""
    d = abs(r_a - r_b)
    p_upset = 1.0 / (10 ** (d * math.sqrt(n) / 2000) + 1.0)
    return p_upset if r_a < r_b else 1.0 - p_upset


def team_strength(team: dict) -> float:
    k = sum(p["K"] for p in team["players"])
    return sum(p["K"] * p["rating"] for p in team["players"]) / k


def ekv_distribution(p: float, n: int = config.GAMES_PER_MATCH) -> list[float]:
    return [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]


def poisson_binomial(ps: list[float]) -> list[float]:
    """Distribution of games won when board i is won with probability ps[i]."""
    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for k, x in enumerate(dist):
            nxt[k] += x * (1 - p)
            nxt[k + 1] += x * p
        dist = nxt
    return dist


def board_probs(m: dict, strength: dict, ratings: dict) -> list[float] | None:
    """Board-by-board win probabilities if a lineup is announced, else None.

    A missing player (partial lineup) falls back to that team's strength.
    """
    lineup = m.get("lineup")
    if not lineup:
        return None
    ps = []
    for b in lineup:
        rh = ratings.get(str(b["home_dbgfnr"]), strength[m["home"]])
        ra = ratings.get(str(b["away_dbgfnr"]), strength[m["away"]])
        ps.append(game_win_prob(rh, ra))
    return ps


def cumulative(dist: list[float]) -> list[float]:
    out, acc = [], 0.0
    for x in dist:
        acc += x
        out.append(acc)
    out[-1] = 1.0
    return out


def sample(cdf: list[float], rng: random.Random) -> int:
    u = rng.random()
    for k, c in enumerate(cdf):
        if u < c:
            return k
    return len(cdf) - 1


def mp(a: int, b: int) -> int:
    return 2 if a > b else 1 if a == b else 0


def rank(teams: list[int], ekv: dict, pts: dict, h2h: dict, rng: random.Random) -> list[int]:
    """Order teams per § 3.3. h2h[(a, b)] = (EKV for a, MP for a) against b."""
    groups: dict[tuple, list[int]] = {}
    for t in teams:
        groups.setdefault((ekv[t], pts[t]), []).append(t)
    order: list[int] = []
    for key in sorted(groups, reverse=True):
        g = groups[key]
        if len(g) > 1:
            def mini(t):
                e = sum(h2h.get((t, o), (0, 0))[0] for o in g if o != t)
                m = sum(h2h.get((t, o), (0, 0))[1] for o in g if o != t)
                return (e, m, rng.random())
            g = sorted(g, key=mini, reverse=True)
        order.extend(g)
    return order


def run(season: dict, n_sims: int = config.N_SIMULATIONS, seed: int = config.RANDOM_SEED) -> dict:
    rng = random.Random(seed)
    teams = [t["id"] for t in season["teams"]]
    name = {t["id"]: t["name"] for t in season["teams"]}
    strength = {t["id"]: team_strength(t) for t in season["teams"]}
    n = len(teams)
    games = config.GAMES_PER_MATCH
    ratings = season.get("player_ratings", {})

    base_ekv = {t: 0 for t in teams}
    base_pts = {t: 0 for t in teams}
    base_k = {t: 0 for t in teams}
    base_h2h: dict[tuple, list[int]] = {}
    remaining = []
    for m in season["matches"]:
        h, a = m["home"], m["away"]
        if m["played"]:
            he, ae = m["home_ekv"], m["away_ekv"]
            base_ekv[h] += he; base_ekv[a] += ae
            base_pts[h] += mp(he, ae); base_pts[a] += mp(ae, he)
            base_k[h] += 1; base_k[a] += 1
            for x, y, xe, ye in ((h, a, he, ae), (a, h, ae, he)):
                r = base_h2h.setdefault((x, y), [0, 0])
                r[0] += xe; r[1] += mp(xe, ye)
        else:
            bp = board_probs(m, strength, ratings)
            dist = poisson_binomial(bp) if bp else ekv_distribution(game_win_prob(strength[h], strength[a]))
            remaining.append(dict(home=h, away=a, date=m["date"], lineup=bool(m.get("lineup")),
                                   dist=dist, cdf=cumulative(dist)))

    cdf_cache: dict[tuple, list[float]] = {}

    def match_cdf(a: int, b: int) -> list[float]:
        if (a, b) not in cdf_cache:
            cdf_cache[(a, b)] = cumulative(ekv_distribution(game_win_prob(strength[a], strength[b])))
        return cdf_cache[(a, b)]

    max_ekv = games * 2 * (n - 1) + games * (config.FINAL_FOUR_SIZE - 1)
    max_pts = 2 * 2 * (n - 1) + 2 * (config.FINAL_FOUR_SIZE - 1)
    stats = {t: dict(
        reg_pos=[0] * n, final_pos=[0] * n,
        reg_ekv=[0] * (max_ekv + 1), final_ekv=[0] * (max_ekv + 1),
        reg_pts=[0] * (max_pts + 1),
        title=0, final4=0, relegated=0) for t in teams}

    # Per-simulation event vector: which teams got the title / final four /
    # relegation, packed as one big integer with a fixed-width bit field per
    # (team, event) so that acc[match][home EKV] += vec tallies all 36 counts
    # in a single addition (see remaining_matches below).
    EVENTS = ("title", "final4", "relegated")
    field_width = max(20, n_sims.bit_length() + 1)
    field_mask = (1 << field_width) - 1
    field = {(t, e): (i * len(EVENTS) + j) * field_width
             for i, t in enumerate(teams) for j, e in enumerate(EVENTS)}
    vec_cache: dict[tuple, int] = {}

    match_acc = [[0] * (games + 1) for _ in remaining]      # [match][home EKV] -> packed vec sum
    outcome_count = [[0] * (games + 1) for _ in remaining]  # [match][home EKV] -> sim count
    sim_outcomes = [0] * len(remaining)                     # home EKV this sim per match

    for _ in range(n_sims):
        ekv = dict(base_ekv); pts = dict(base_pts)
        h2h = {k: list(v) for k, v in base_h2h.items()}
        for i, m in enumerate(remaining):
            h, a = m["home"], m["away"]
            he = sample(m["cdf"], rng); ae = games - he
            ekv[h] += he; ekv[a] += ae
            ph, pa = mp(he, ae), mp(ae, he)
            pts[h] += ph; pts[a] += pa
            r = h2h.setdefault((h, a), [0, 0]); r[0] += he; r[1] += ph
            r = h2h.setdefault((a, h), [0, 0]); r[0] += ae; r[1] += pa
            sim_outcomes[i] = he
            outcome_count[i][he] += 1

        order = rank(teams, ekv, pts, h2h, rng)
        for pos, t in enumerate(order):
            s = stats[t]
            s["reg_pos"][pos] += 1
            s["reg_ekv"][ekv[t]] += 1
            s["reg_pts"][pts[t]] += 1
            if pos >= n - config.RELEGATED:
                s["relegated"] += 1

        f4 = order[:config.FINAL_FOUR_SIZE]
        for i, x in enumerate(f4):
            stats[x]["final4"] += 1
            for y in f4[i + 1:]:
                xe = sample(match_cdf(x, y), rng); ye = games - xe
                ekv[x] += xe; ekv[y] += ye
                px, py = mp(xe, ye), mp(ye, xe)
                pts[x] += px; pts[y] += py
                r = h2h.setdefault((x, y), [0, 0]); r[0] += xe; r[1] += px
                r = h2h.setdefault((y, x), [0, 0]); r[0] += ye; r[1] += py
        final_order = rank(f4, ekv, pts, h2h, rng) + order[config.FINAL_FOUR_SIZE:]
        title_team = final_order[0]
        stats[title_team]["title"] += 1
        for pos, t in enumerate(final_order):
            stats[t]["final_pos"][pos] += 1
            stats[t]["final_ekv"][ekv[t]] += 1

        releg = order[n - config.RELEGATED:]
        sig = (title_team, frozenset(f4), frozenset(releg))
        vec = vec_cache.get(sig)
        if vec is None:
            vec = 1 << field[(title_team, "title")]
            for t in f4:
                vec |= 1 << field[(t, "final4")]
            for t in releg:
                vec |= 1 << field[(t, "relegated")]
            vec_cache[sig] = vec
        for i in range(len(remaining)):
            match_acc[i][sim_outcomes[i]] += vec

    def norm(xs):
        return [x / n_sims for x in xs]

    def mean(hist):
        tot = sum(hist)
        return sum(i * c for i, c in enumerate(hist)) / tot if tot else None

    def trim(hist):
        """Normalise and trim empty tails; returns {start, p}."""
        nz = [i for i, c in enumerate(hist) if c]
        if not nz:
            return {"start": 0, "p": []}
        lo, hi = nz[0], nz[-1]
        return {"start": lo, "p": [c / n_sims for c in hist[lo:hi + 1]]}

    std_by_id = {r["id"]: r for r in season["standings"]}
    # Current place as listed on backgammon.dk (sorted by +/- while teams have
    # played different numbers of matches).
    position = {r["id"]: i + 1 for i, r in enumerate(season["standings"])}
    team_out = []
    for t in season["teams"]:
        tid = t["id"]; s = stats[tid]
        st = std_by_id[tid]
        fixtures = []
        for m in season["matches"]:
            if tid not in (m["home"], m["away"]):
                continue
            home = m["home"] == tid
            opp = m["away"] if home else m["home"]
            f = dict(date=m["date"], home=home, opponent=opp, opponent_name=name[opp],
                     played=m["played"], venue=m.get("venue"))
            if m["played"]:
                f["ekv_for"] = m["home_ekv"] if home else m["away_ekv"]
                f["ekv_against"] = m["away_ekv"] if home else m["home_ekv"]
            else:
                bp = board_probs(m, strength, ratings)
                if bp:
                    d = poisson_binomial(bp if home else [1 - x for x in bp])
                    def r(nr):
                        return ratings.get(str(nr)) if nr is not None else None
                    f["lineup"] = [dict(
                        me=b["home_player"] if home else b["away_player"],
                        opp=b["away_player"] if home else b["home_player"],
                        me_dbgfnr=b["home_dbgfnr"] if home else b["away_dbgfnr"],
                        opp_dbgfnr=b["away_dbgfnr"] if home else b["home_dbgfnr"],
                        me_rating=r(b["home_dbgfnr"] if home else b["away_dbgfnr"]),
                        opp_rating=r(b["away_dbgfnr"] if home else b["home_dbgfnr"]),
                        p=x if home else 1 - x) for b, x in zip(m["lineup"], bp)]
                else:
                    d = ekv_distribution(game_win_prob(strength[tid], strength[opp]))
                f["p_win"] = d[3] + d[4]
                f["p_draw"] = d[2]
                f["p_loss"] = d[0] + d[1]
                f["exp_ekv"] = sum(k * x for k, x in enumerate(d))
            fixtures.append(f)
        team_out.append(dict(
            id=tid, name=t["name"], url=t["url"],
            position=position[tid],
            strength=strength[tid],
            players=sorted(t["players"], key=lambda p: (-p["K"], -p["rating"])),
            current=dict(K=st["K"], V=st["V"], U=st["U"], T=st["T"], EKV=st["EKV"],
                         EKT=st["EKT"], P=st["P"], pm=st["pm"]),
            p_title=s["title"] / n_sims,
            p_final4=s["final4"] / n_sims,
            p_relegated=s["relegated"] / n_sims,
            p_title_given_final4=(s["title"] / s["final4"]) if s["final4"] else None,
            reg_pos=norm(s["reg_pos"]),
            final_pos=norm(s["final_pos"]),
            exp_reg_pos=1 + mean(s["reg_pos"]),
            exp_reg_ekv=mean(s["reg_ekv"]),
            exp_reg_pts=mean(s["reg_pts"]),
            reg_ekv=trim(s["reg_ekv"]),
            reg_pts=trim(s["reg_pts"]),
            final_ekv=trim(s["final_ekv"]),
            fixtures=fixtures,
        ))

    def unpack(vec: int) -> dict:
        """Per-(team, event) counts encoded in a packed vec (see match_acc above)."""
        return {key: (vec >> shift) & field_mask for key, shift in field.items()}

    remaining_matches = []
    for i, m in enumerate(remaining):
        h, a = m["home"], m["away"]
        dist = m["dist"]
        p = [round(dist[3] + dist[4], 4), round(dist[2], 4), round(dist[0] + dist[1], 4)]
        exp_home_ekv = round(sum(k * x for k, x in enumerate(dist)), 4)
        counts = outcome_count[i]
        decoded = [unpack(acc) for acc in match_acc[i]]

        def cond_of(t):
            return {e: [round(decoded[k][(t, e)] / counts[k], 4) if counts[k] else None
                        for k in range(games + 1)] for e in EVENTS}

        remaining_matches.append(dict(
            home=h, away=a, date=m["date"], lineup=m["lineup"],
            p=p, exp_home_ekv=exp_home_ekv,
            dist=[round(x, 4) for x in dist],
            cond=dict(home=cond_of(h), away=cond_of(a)),
        ))
    remaining_matches.sort(key=lambda r: (r["date"] is None, r["date"] or "", r["home"]))

    now = datetime.now(timezone.utc).astimezone()
    return dict(
        generated_at=now.isoformat(timespec="seconds"),
        scraped_at=season["scraped_at"],
        season_label=config.SEASON_LABEL,
        source=season["source"],
        github_url=config.GITHUB_URL,
        n_simulations=n_sims,
        n_matches_total=len(season["matches"]),
        n_matches_played=sum(m["played"] for m in season["matches"]),
        next_match_date=next_match_date(season["matches"]),
        final_four_date=config.FINAL_FOUR_DATE,
        relegated=config.RELEGATED,
        final_four_size=config.FINAL_FOUR_SIZE,
        match_length=config.MATCH_LENGTH,
        games_per_match=games,
        teams=team_out,
        remaining_matches=remaining_matches,
    )


def next_match_date(matches: list[dict]) -> str | None:
    """Earliest date among unplayed matches. A postponed match may have no date yet."""
    return min((m["date"] for m in matches if not m["played"] and m["date"]), default=None)


def update_history(results: dict) -> list[dict]:
    """One entry per day (the latest run that day wins)."""
    hist = json.loads(HISTORY_JSON.read_text(encoding="utf-8")) if HISTORY_JSON.exists() else []
    day = results["generated_at"][:10]
    entry = dict(date=day, n_matches_played=results["n_matches_played"],
                 teams={str(t["id"]): dict(title=round(t["p_title"], 4),
                                           final4=round(t["p_final4"], 4),
                                           relegated=round(t["p_relegated"], 4),
                                           strength=round(t["strength"], 2))
                        for t in results["teams"]})
    hist = [h for h in hist if h["date"] != day] + [entry]
    hist.sort(key=lambda h: h["date"])
    HISTORY_JSON.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    return hist
