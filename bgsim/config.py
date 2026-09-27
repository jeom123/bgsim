"""Simulation settings. Update these when a new season starts."""

# backgammon.dk: season=37 is 2026/2027, division=118 is Elitedivisionen.
SEASON_ID = 37
DIVISION_ID = 118
SEASON_LABEL = "2026/2027"

# Each team match is 4 individual games to 17 points (regulations § 5.1).
GAMES_PER_MATCH = 4
MATCH_LENGTH = 17

# Final four: the top four after the regular season meet each other once more
# (3 extra team matches each). Points are added to the regular-season totals
# (as in 2025/26, when the top four finished on 25 matches). Saturday 3 April 2027.
FINAL_FOUR_SIZE = 4
FINAL_FOUR_DATE = "2027-04-03"

# Relegation: places 10-12 after the regular season go down directly. The
# 2026-27 structure document is not yet published ("tilgår"), but in 2025/26
# places 10-12 went down directly and no Elitedivisionen team played a play-off.
RELEGATED = 3

N_SIMULATIONS = 100_000
RANDOM_SEED = 20260917

REQUEST_DELAY_S = 1.0
FETCH_ATTEMPTS = 4          # per page, for transient network failures
FETCH_RETRY_DELAY_S = 10.0  # waits 10 s, 20 s, 30 s between attempts

GITHUB_URL = "https://github.com/jeom123/bgsim"
