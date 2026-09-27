"""Fetches and parses Elitedivisionen from backgammon.dk.

Saves raw HTML in data/raw/ and a parsed snapshot in data/season.json.
Uses the standard library only.

backgammon.dk runs ModSecurity (a web application firewall) that blocks the
default curl/urllib User-Agent, so a browser User-Agent is sent. Requests are
spaced out so the server is not loaded.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import config

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SEASON_JSON = ROOT / "data" / "season.json"

BASE = "https://www.backgammon.dk"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

MONTHS = {"januar": 1, "februar": 2, "marts": 3, "april": 4, "maj": 5, "juni": 6,
          "juli": 7, "august": 8, "september": 9, "oktober": 10,
          "november": 11, "december": 12}


def fetch(url: str, name: str, offline: bool = False) -> str:
    path = RAW / f"{name}.html"
    if offline:
        return path.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html", "Accept-Language": "da,en"})
    # Retry transient network failures (connection resets and timeouts have
    # been seen through the cloud sandbox proxy). HTTP errors are not retried.
    for attempt in range(config.FETCH_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError):
            if attempt == config.FETCH_ATTEMPTS - 1:
                raise
            time.sleep(config.FETCH_RETRY_DELAY_S * (attempt + 1))
    if "ModSecurity" in body[:3000]:
        raise RuntimeError(f"Blocked by ModSecurity: {url}")
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    time.sleep(config.REQUEST_DELAY_S)
    return body


def initials(name: str | None) -> str | None:
    """Player names are not published: "Anna-Lisa Example" -> "ALE"."""
    if not name:
        return None
    parts = [p for p in re.split(r"[\s\-]+", name) if p and p[0].isalpha()]
    return "".join(p[0].upper() for p in parts) or None


def member_url(dbgfnr: int) -> str:
    return f"{BASE}/Rating/S%C3%B8g+medlem?dbgfnr={dbgfnr}"


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_standings(page: str) -> tuple[list[dict], dict[int, str]]:
    """Returns the standings as shown on the site, and team id -> name."""
    names: dict[int, str] = {}
    rows = []
    tbl = page.split("Stillingen", 1)[-1]
    tbl = tbl.split("Topscorere", 1)[0]
    for tr in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", tbl):
        m = re.search(r"hold=(\d+)\"?[^>]*>([^<]+)</a>", tr)
        if not m:
            continue
        hid, name = int(m.group(1)), html.unescape(m.group(2)).strip()
        names[hid] = name
        tds = [clean(x) for x in re.findall(r"(?s)<td[^>]*>(.*?)</td>", tr)]
        # +/- can be a decimal ("2,5") while a match is in progress.
        nums = [t for t in tds if re.fullmatch(r"-?\d+(?:,\d+)?", t)]
        # Last 8 numbers: K V U T EKV EKT P +/-
        k, v, u, t, ekv, ekt, p = map(int, nums[-8:-1])
        pm = float(nums[-1].replace(",", "."))
        pm = int(pm) if pm.is_integer() else pm
        rows.append(dict(id=hid, name=name, K=k, V=v, U=u, T=t, EKV=ekv,
                         EKT=ekt, P=p, pm=pm))
    return rows, names


def parse_team(page: str) -> list[dict]:
    """Players who have played for the team so far: rating and games played (K)."""
    sec = page.split("Individuelle resultater", 1)[1].split("</table>", 1)[0]
    players = []
    for tr in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", sec):
        m = re.search(r"dbgfnr=(\d+)", tr)
        if not m:
            continue
        tds = [clean(x) for x in re.findall(r"(?s)<td[^>]*>(.*?)</td>", tr)]
        # [no, dbgfnr, name (+title), rating, K, V, T, +/-]
        name = tds[2]
        title = None
        tm = re.search(r"\s(SGM|GM|IM|WC)$", name)
        if tm:
            title, name = tm.group(1), name[:tm.start()].strip()
        players.append(dict(dbgfnr=int(m.group(1)), initials=initials(name), title=title,
                            rating=float(tds[3].replace(".", "").replace(",", ".")),
                            K=int(tds[4]), V=int(tds[5]), T=int(tds[6])))
    return players


def member_rating(dbgfnr: int, offline: bool = False) -> float:
    url = member_url(dbgfnr)
    page = fetch(url, f"medlem_{dbgfnr}", offline)
    m = re.search(r"(?s)<td>Rating</td>\s*<td[^>]*>\s*([\d.,]+)", page)
    if not m:
        raise RuntimeError(f"No rating found for member {dbgfnr}")
    return float(m.group(1).replace(".", "").replace(",", "."))


def parse_date(s: str) -> str | None:
    m = re.search(r"d\.\s*(\d+)\.\s*(\w+)\s+(\d{4})(?:\s*kl\.\s*(\d+):(\d+))?", s)
    if not m:
        return None
    d, mon, y = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
    hh, mm = int(m.group(4) or 0), int(m.group(5) or 0)
    return f"{y:04d}-{mon:02d}-{d:02d}T{hh:02d}:{mm:02d}"


def parse_program(page: str) -> list[dict]:
    """All regular-season team matches, played and unplayed."""
    matches = []
    body = page.split("Kampe &#8211; Alle", 1)[-1]
    # Split into date blocks (h5), then into match-group blocks.
    parts = re.split(r'(?s)<h5 class="match-collapse-toggle kamphead">(.*?)</h5>', body)
    for i in range(1, len(parts), 2):
        date = parse_date(clean(parts[i]))
        for grp in re.split(r'<div class="match-group kampdesc">', parts[i + 1])[1:]:
            teams = re.findall(r"hold=(\d+)\">", grp[:1500])
            if len(teams) < 2:
                continue
            home, away = int(teams[0]), int(teams[1])
            head = grp.split('individual-matches', 1)[0]
            sm = re.search(r"<span>\s*(\d+)\s*&#8211;\s*(\d+)\s*</span>", head)
            venue = None
            vm = re.search(r"Spillested:\s*([^<]+)", grp[:3000])
            if vm:
                venue = clean(vm.group(1))
            games = []
            for tr in re.findall(r"(?s)<tr>(.*?)</tr>", grp.split("</table>", 1)[0]):
                tds = re.findall(r"(?s)<td[^>]*>(.*?)</td>", tr)
                if len(tds) != 5:
                    continue
                hp, hs, _, as_, ap = tds
                hn = re.search(r"\b(\d{1,6})\b", clean(hp.split("<br>")[-1]) if "<br>" in hp else "")
                an = re.search(r"\b(\d{1,6})\b", clean(ap.split("<br>")[-1]) if "<br>" in ap else "")
                games.append(dict(
                    home_player=initials(clean(hp.split("<br>")[0])),
                    home_dbgfnr=int(hn.group(1)) if hn else None,
                    away_player=initials(clean(ap.split("<br>")[0])),
                    away_dbgfnr=int(an.group(1)) if an else None,
                    home_score=int(clean(hs) or 0), away_score=int(clean(as_) or 0)))
            # A match with an announced lineup but no result shows as "0 – 0".
            # One with fewer than all games decided is in progress: the site
            # already counts its partial score in the table, but it is
            # simulated as unplayed with its lineup.
            he, ae = (int(sm.group(1)), int(sm.group(2))) if sm else (0, 0)
            played = he + ae == config.GAMES_PER_MATCH
            m = dict(date=date, home=home, away=away, played=played, venue=venue)
            if played:
                m["home_ekv"], m["away_ekv"] = he, ae
                m["games"] = games
            elif he + ae:
                m["in_progress"] = dict(home_ekv=he, away_ekv=ae)
            if not played and any(g["home_dbgfnr"] or g["away_dbgfnr"] for g in games):
                # Lineup entered before the match (unusual). May be partial:
                # the away team fills in first, then the home team (§ 5.4).
                m["lineup"] = [dict(home_player=g["home_player"], home_dbgfnr=g["home_dbgfnr"],
                                    away_player=g["away_player"], away_dbgfnr=g["away_dbgfnr"])
                               for g in games]
            matches.append(m)
    return matches


def scrape(offline: bool = False) -> dict:
    s, d = config.SEASON_ID, config.DIVISION_ID
    stand_url = f"{BASE}/KT%2bSenesteS%C3%A6son?season={s}&division={d}"
    prog_url = f"{BASE}/KT%2bSenesteS%C3%A6son?view=HoldKampprogram&season={s}&division={d}&matchtype=0"
    standings, names = parse_standings(fetch(stand_url, "stilling", offline))
    matches = parse_program(fetch(prog_url, "kampprogram", offline))
    teams = []
    for hid, name in names.items():
        url = f"{BASE}/KT%2bSenesteS%C3%A6son?view=HoldVisning&season={s}&division={d}&hold={hid}"
        players = parse_team(fetch(url, f"hold_{hid}", offline))
        teams.append(dict(id=hid, name=name, players=players, url=url))
    # Ratings for players in announced lineups: from the team pages, or from
    # the member page for players who have not played for the team yet.
    known = {p["dbgfnr"]: p["rating"] for t in teams for p in t["players"]}
    ratings: dict[str, float] = {}
    for m in matches:
        for b in m.get("lineup", []):
            for nr in (b["home_dbgfnr"], b["away_dbgfnr"]):
                if nr is None or str(nr) in ratings:
                    continue
                if nr in known:
                    ratings[str(nr)] = known[nr]
                else:
                    ratings[str(nr)] = member_rating(nr, offline)
    data = dict(
        player_ratings=ratings,
        scraped_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        season_id=s, division_id=d, source=stand_url,
        standings=standings, teams=teams, matches=matches)
    validate(data)
    SEASON_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def validate(data: dict) -> None:
    """Check that standings computed from the matches equal the site's table."""
    agg = {t["id"]: dict(K=0, EKV=0, EKT=0, P=0) for t in data["teams"]}
    for m in data["matches"]:
        if m["played"]:
            he, ae = m["home_ekv"], m["away_ekv"]
        elif "in_progress" in m:  # the site counts the partial score
            he, ae = m["in_progress"]["home_ekv"], m["in_progress"]["away_ekv"]
        else:
            continue
        for me, op, a, b in ((m["home"], m["away"], he, ae),
                             (m["away"], m["home"], ae, he)):
            r = agg[me]
            r["K"] += 1; r["EKV"] += a; r["EKT"] += b
            r["P"] += 2 if a > b else 1 if a == b else 0
    problems = []
    for row in data["standings"]:
        mine = agg[row["id"]]
        for k in ("K", "EKV", "EKT", "P"):
            if mine[k] != row[k]:
                problems.append(f"{row['name']}: {k} {mine[k]} != {row[k]}")
    n = len(data["teams"])
    if len(data["matches"]) != n * (n - 1):
        problems.append(f"{len(data['matches'])} matches in the schedule, expected {n*(n-1)}")
    for t in data["teams"]:
        if sum(p["K"] for p in t["players"]) == 0:
            problems.append(f"{t['name']}: no games played")
    if problems:
        raise RuntimeError("Validation failed:\n  " + "\n  ".join(problems))
