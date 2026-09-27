import unittest
from unittest import mock

from bgsim import config
from bgsim.simulate import run


def make_team(tid, name, rating):
    return dict(id=tid, name=name, url="", players=[dict(K=100, rating=rating)])


def make_standing(tid):
    return dict(id=tid, K=0, V=0, U=0, T=0, EKV=0, EKT=0, P=0, pm=0)


def played(home, away, home_ekv, away_ekv):
    return dict(home=home, away=away, played=True, date=None, venue=None,
                home_ekv=home_ekv, away_ekv=away_ekv)


def unplayed(home, away, date):
    return dict(home=home, away=away, played=False, date=date, venue=None)


# Synthetic 6-team season: A, B, C, D are locked into the top 4 (final four) by
# big base margins from already-played matches; E and F are locked into the
# bottom 2 (relegated, with RELEGATED patched to 2 for this test) by equally
# big margins. Two matches remain: A-C (can still swing who ends up on top
# among the already-safe final-four teams) and E-F (can only swap E and F
# between themselves, both already relegated either way).
A, B, C, D, E, F = 1, 2, 3, 4, 5, 6


def make_season():
    teams = [make_team(A, "A", 1400), make_team(B, "B", 1350), make_team(C, "C", 1300),
              make_team(D, "D", 1250), make_team(E, "E", 1000), make_team(F, "F", 950)]
    standings = [make_standing(t) for t in (A, B, C, D, E, F)]
    matches = [
        played(A, E, 4, 0), played(B, E, 4, 0),
        played(C, F, 4, 0), played(D, F, 4, 0),
        played(A, B, 3, 1), played(C, D, 3, 1),
        unplayed(A, C, "2027-01-01T00:00"),
        unplayed(E, F, "2026-12-01T00:00"),
    ]
    return dict(teams=teams, matches=matches, standings=standings,
                player_ratings={}, scraped_at="2026-01-01T00:00:00+00:00", source="test")


def make_deterministic_season():
    """A season where only E-F is unplayed and every other outcome (final
    four membership, the final-four matches, the champion) is fixed by
    construction (huge rating gaps make every other match a sure thing), so
    the only randomness in the whole simulation is the E-F result.
    """
    teams = [make_team(A, "A", 100_000), make_team(B, "B", 90_000), make_team(C, "C", 80_000),
              make_team(D, "D", 70_000), make_team(E, "E", 1_000), make_team(F, "F", 900)]
    standings = [make_standing(t) for t in (A, B, C, D, E, F)]
    matches = [
        played(A, B, 3, 1), played(A, C, 3, 1), played(A, D, 3, 1),
        played(B, C, 3, 1), played(B, D, 3, 1), played(C, D, 3, 1),
        played(A, E, 4, 0), played(B, E, 4, 0), played(C, E, 4, 0), played(D, E, 4, 0),
        played(A, F, 4, 0), played(B, F, 4, 0), played(C, F, 4, 0), played(D, F, 4, 0),
        unplayed(E, F, "2026-12-01T00:00"),
    ]
    return dict(teams=teams, matches=matches, standings=standings,
                player_ratings={}, scraped_at="2026-01-01T00:00:00+00:00", source="test")


class RemainingMatchesSchema(unittest.TestCase):
    def setUp(self):
        # 6 teams: patch RELEGATED so the bottom two are relegated without
        # overlapping the (unpatched) top-4 final-four cut.
        self.patcher = mock.patch.object(config, "RELEGATED", 2)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.season = make_season()
        self.results = run(self.season, n_sims=5000, seed=1)

    def test_top_level_keys_present(self):
        self.assertIn("remaining_matches", self.results)

    def test_remaining_matches_schema_and_order(self):
        rm = self.results["remaining_matches"]
        self.assertEqual(len(rm), 2)
        # Sorted by date: E-F (Dec) before A-C (Jan).
        self.assertEqual([(m["home"], m["away"]) for m in rm], [(E, F), (A, C)])
        for m in rm:
            for key in ("home", "away", "date", "lineup", "p", "exp_home_ekv",
                        "cond", "importance", "importance_by"):
                self.assertIn(key, m)
            self.assertEqual(len(m["p"]), 3)
            self.assertAlmostEqual(sum(m["p"]), 1.0, places=4)
            for side in ("home", "away"):
                for ev in ("title", "final4", "relegated"):
                    self.assertIn(ev, m["cond"][side])
                    self.assertEqual(len(m["cond"][side][ev]), 3)
            for ev in ("title", "final4", "relegated"):
                self.assertIn(ev, m["importance_by"])
            self.assertAlmostEqual(m["importance"], sum(m["importance_by"].values()), places=4)

    def test_importance_zero_for_match_that_cannot_matter(self):
        # Use a season where E-F is the only unplayed match and every other
        # outcome is deterministic, so there is no other source of variance
        # that could leak a spurious nonzero importance from sampling noise.
        results = run(make_deterministic_season(), n_sims=5000, seed=1)
        rm = {(m["home"], m["away"]): m for m in results["remaining_matches"]}
        ef = rm[(E, F)]
        self.assertEqual(ef["importance"], 0.0)
        for ev in ("title", "final4", "relegated"):
            self.assertEqual(ef["importance_by"][ev], 0.0)
        for side in ("home", "away"):
            self.assertEqual(ef["cond"][side]["title"], [0.0, 0.0, 0.0])
            self.assertEqual(ef["cond"][side]["final4"], [0.0, 0.0, 0.0])
            self.assertEqual(ef["cond"][side]["relegated"], [1.0, 1.0, 1.0])

    def test_cond_consistent_with_unconditional_totals(self):
        # sum over outcomes of freq(outcome) * cond(event | outcome) should
        # match the unconditional per-team probability. The exact model "p"
        # is used as a stand-in for the simulated outcome frequency, which
        # should be close for a large enough n_sims.
        p_title = {t["id"]: t["p_title"] for t in self.results["teams"]}
        p_final4 = {t["id"]: t["p_final4"] for t in self.results["teams"]}
        p_relegated = {t["id"]: t["p_relegated"] for t in self.results["teams"]}
        for m in self.results["remaining_matches"]:
            for side, tid in (("home", m["home"]), ("away", m["away"])):
                for ev, uncond in (("title", p_title), ("final4", p_final4),
                                   ("relegated", p_relegated)):
                    vals = m["cond"][side][ev]
                    weighted = sum((v or 0.0) * w for v, w in zip(vals, m["p"]))
                    self.assertAlmostEqual(weighted, uncond[tid], delta=0.03)


if __name__ == "__main__":
    unittest.main()
