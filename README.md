# Elitedivisionen backgammon simulation

Monte Carlo simulation of the rest of the Danish backgammon club league, Elitedivisionen
of Klubturneringen (the Danish club championship), season 2026/2027. The output is a
static web page in `docs/index.html` showing each team's chances of winning the title,
reaching the final four and being relegated.

**Live page: https://jeom123.github.io/bgsim/** (GitHub Pages, served from `docs/` on `main`).

## Running

Requires only Python 3.10+ (no external packages).

```sh
python3 run.py              # fetch from backgammon.dk, simulate, build the page
python3 run.py --offline    # reuse the saved raw pages in data/raw/
python3 run.py -n 20000     # fewer simulations
python3 run.py --build-only # rebuild the page only
python3 run.py --if-changed # stop unless results or lineups changed (prints NO_NEW_DATA)
python3 -m unittest discover -s tests -t .
```

## Pipeline

| Step | File | Output |
|---|---|---|
| Fetch and parse | `bgsim/scrape.py` | `data/raw/*.html`, `data/season.json` |
| Simulate | `bgsim/simulate.py` | `data/results.json`, `data/history.json` |
| Build page | `bgsim/build.py` + `bgsim/template.html` | `docs/index.html`, `build/artifact.html` |

Settings (season, division, number of relegated teams, number of simulations) live in
`bgsim/config.py`. `data/history.json` gets one entry per run day and drives the trend
charts.

## Model

- **Team strength**: the average rating of the players who have played for the team so
  far, weighted by the number of individual games each has played.
- **Single-game win probability** from the DBgF rating formula
  ([Beregning af rating](https://www.backgammon.dk/Rangliste/Beregning+af+rating)):
  `P_upset = 1 / (10^(D·√N/2000) + 1)` with match length N = 17.
- **Team match**: four independent individual games. When a lineup has already been
  entered on backgammon.dk, the actual players' ratings are used board by board.
  A match in progress (fewer than four games decided) is simulated as unplayed with
  its lineup; the partial score is only used to validate against the site's table.
- **Scoring** (regulations § 5.10): 1 EKV per individual game won, 2 MP (match points)
  for a team match win, 1 MP for a 2–2 draw.
- **Ranking** (§ 3.3): 1) EKV, 2) MP, 3) head-to-head (EKV, then MP, in the matches
  between the tied teams), 4) play-off match, modelled as a random draw.
- **Final four**: the top four after the regular season meet each other once more on
  3 April 2027. EKV and MP are added to the regular-season totals. The leader after the
  final four is Danish champion.
- **Relegation**: places 10–12 after the regular season go down directly.

## Additional simulation output

`data/results.json` also carries a field aimed at explaining *why* a result
is likely, beyond each team's own probabilities:

- `remaining_matches`: one entry per unplayed regular-season match, with its
  exact score distribution (`dist`, home EKV 0–4), win/draw/loss probabilities
  and expected home EKV, plus each team's title / final-four / relegation
  chance conditional on each exact score (`cond`, indexed by home EKV 0–4).

## Sources and assumptions

- Player names are not published. The scraper keeps only initials and the DBgF member
  number, and the page links each player to their member page on backgammon.dk.

- [Reglement for Klubturneringen for hold (Aug 2026)](https://www.backgammon.dk/Regler+mv/Turneringsregler),
  text copy in `data/reglement-klubturneringen-aug-2026.txt`.
- [Key dates KT 2026-27](https://www.backgammon.dk/Forum?view=Traad&id=1660):
  last regular-season round 13 March, final four 3 April 2027.
- The 2026-27 promotion/relegation structure document is not yet published. Direct
  relegation of three teams follows 2025/26, when places 10–12 went down and no
  Elitedivisionen team played a play-off. Adding final-four points to the regular-season
  totals follows the 2025/26 final table.
- backgammon.dk runs a web application firewall (ModSecurity) that blocks default
  client User-Agents, so the scraper sends a browser User-Agent and waits one second
  between requests.
