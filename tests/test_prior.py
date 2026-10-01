import unittest
from unittest import mock

from bgsim import config
from bgsim.scrape import match_previous, team_key, validate
from bgsim.simulate import prior_weight, run, team_strength, weighted_rating


def squad(*pairs):
    """Players from (K, rating) pairs."""
    return [dict(K=k, rating=r) for k, r in pairs]


class PriorWeight(unittest.TestCase):
    def test_start_of_season_is_all_prior(self):
        self.assertEqual(prior_weight(0.0), 1.0)

    def test_fades_linearly(self):
        self.assertAlmostEqual(prior_weight(0.33), 0.5, places=2)

    def test_zero_from_fade_out_on(self):
        self.assertEqual(prior_weight(0.66), 0.0)

    def test_never_negative(self):
        self.assertEqual(prior_weight(1.0), 0.0)


class WeightedRating(unittest.TestCase):
    def test_k_weighted_mean(self):
        players = squad((1, 1000), (3, 1400))
        self.assertAlmostEqual(weighted_rating(players), (1000 + 3 * 1400) / 4)

    def test_none_when_nobody_played(self):
        self.assertIsNone(weighted_rating(squad((0, 1200), (0, 1500))))

    def test_none_when_empty(self):
        self.assertIsNone(weighted_rating([]))


class TeamStrength(unittest.TestCase):
    def team(self, now=((10, 1200),), prev=((10, 1400),)):
        t = dict(id=1, name="T", players=squad(*now))
        if prev is not None:
            t["previous"] = dict(players=squad(*prev))
        return t

    def test_blend_of_both_seasons(self):
        f = 0.33
        w = prior_weight(f)
        out = team_strength(self.team(), f)
        self.assertEqual(set(out), {"strength", "strength_now", "strength_prev", "prior_weight"})
        self.assertAlmostEqual(out["prior_weight"], w)
        self.assertAlmostEqual(out["strength_now"], 1200)
        self.assertAlmostEqual(out["strength_prev"], 1400)
        self.assertAlmostEqual(out["strength"], w * 1400 + (1 - w) * 1200)

    def test_no_previous_key_uses_this_season(self):
        out = team_strength(self.team(prev=None), 0.0)
        self.assertAlmostEqual(out["strength"], 1200)
        self.assertEqual(out["prior_weight"], 0)
        self.assertIsNone(out["strength_prev"])

    def test_previous_none_uses_this_season(self):
        t = self.team()
        t["previous"] = None
        out = team_strength(t, 0.0)
        self.assertAlmostEqual(out["strength"], 1200)
        self.assertEqual(out["prior_weight"], 0)

    def test_no_games_this_season_uses_last_season(self):
        out = team_strength(self.team(now=((0, 1200),)), 0.5)
        self.assertAlmostEqual(out["strength"], 1400)
        self.assertEqual(out["prior_weight"], 1)
        self.assertIsNone(out["strength_now"])

    def test_previous_ignored_from_fade_out(self):
        for f in (0.66, 0.8, 1.0):
            out = team_strength(self.team(), f)
            self.assertAlmostEqual(out["strength"], 1200)
            self.assertEqual(out["prior_weight"], 0.0)


def make_team(tid, name, rating, prev_players):
    return dict(id=tid, name=name, url="", players=[dict(K=100, rating=rating)],
                previous=dict(id=tid, name=name, url="", season_label="2025/2026",
                              players=prev_players))


def make_standing(tid):
    return dict(id=tid, K=0, V=0, U=0, T=0, EKV=0, EKT=0, P=0, pm=0)


def played(home, away, home_ekv, away_ekv):
    return dict(home=home, away=away, played=True, date=None, venue=None,
                home_ekv=home_ekv, away_ekv=away_ekv)


def unplayed(home, away, date):
    return dict(home=home, away=away, played=False, date=date, venue=None)


class RunUsesOwnMatchesPlayed(unittest.TestCase):
    """6 teams -> 10 regular-season matches each. A has played 3, B, C, D 1, E, F 0."""

    @classmethod
    def setUpClass(cls):
        ids = [1, 2, 3, 4, 5, 6]
        prev = [dict(K=5, rating=1100), dict(K=20, rating=1300), dict(K=10, rating=1200)]
        teams = [make_team(t, str(t), 1200 + 10 * t, [dict(p) for p in prev]) for t in ids]
        matches = [played(1, 2, 3, 1), played(1, 3, 2, 2), played(4, 1, 1, 3),
                   unplayed(5, 6, "2026-12-01T00:00"), unplayed(2, 3, "2026-12-08T00:00")]
        season = dict(teams=teams, matches=matches, standings=[make_standing(t) for t in ids],
                      player_ratings={}, scraped_at="2026-01-01T00:00:00+00:00", source="test")
        with mock.patch.object(config, "RELEGATED", 2):
            cls.results = run(season, n_sims=200, seed=1)
        cls.teams = {t["id"]: t for t in cls.results["teams"]}

    def test_matches_played_and_total(self):
        self.assertEqual({i: t["matches_played"] for i, t in self.teams.items()},
                         {1: 3, 2: 1, 3: 1, 4: 1, 5: 0, 6: 0})
        for t in self.teams.values():
            self.assertEqual(t["matches_total"], 10)

    def test_prior_weight_per_team(self):
        for tid, played_n in ((1, 3), (2, 1), (5, 0)):
            self.assertAlmostEqual(self.teams[tid]["prior_weight"],
                                   max(0.0, 1 - (played_n / 10) / config.PRIOR_FADE_OUT))
        self.assertEqual(self.teams[5]["prior_weight"], 1.0)
        self.assertGreater(self.teams[2]["prior_weight"], self.teams[1]["prior_weight"])

    def test_strength_blends_per_team(self):
        t = self.teams[1]
        w = t["prior_weight"]
        self.assertAlmostEqual(t["strength"], w * t["strength_prev"] + (1 - w) * t["strength_now"])

    def test_previous_passed_through_sorted_by_k(self):
        prev = self.teams[1]["previous"]
        self.assertEqual(prev["season_label"], "2025/2026")
        self.assertEqual([p["K"] for p in prev["players"]], [20, 10, 5])

    def test_top_level_keys(self):
        self.assertEqual(self.results["prior_fade_out"], config.PRIOR_FADE_OUT)
        self.assertEqual(self.results["previous_season_label"], config.PREVIOUS_SEASON_LABEL)


class TeamKey(unittest.TestCase):
    def test_keys(self):
        for name, key in (("Lødigt I (M)", "lødigt"),
                          ("Familien Nemesis (O)", "familien nemesis"),
                          ("Langebro I Langebro", "langebro langebro"),
                          ("Røde Stjerne 2.0", "røde stjerne 2.0")):
            self.assertEqual(team_key(name), key)


class MatchPrevious(unittest.TestCase):
    candidates = {i: dict(id=i, name=n) for i, n in (
        (554, "Lødigt"), (567, "Langebro I Langebro"), (564, "Livingstone (O)"),
        (601, "Odense I Young Stars"), (574, "Odense II Seniors"))}

    def test_matches_by_name(self):
        self.assertEqual(match_previous(dict(id=1, name="Lødigt I (M)"), self.candidates)["id"], 554)
        self.assertEqual(match_previous(dict(id=2, name="Langebro (O)"), self.candidates)["id"], 567)

    def test_ambiguous_raises(self):
        with self.assertRaises(RuntimeError):
            match_previous(dict(id=3, name="Odense I"), self.candidates)

    def test_no_match_raises(self):
        with self.assertRaises(RuntimeError):
            match_previous(dict(id=4, name="Nowhere FC"), self.candidates)

    def test_override_wins_over_name(self):
        with mock.patch.dict(config.PREVIOUS_TEAM_OVERRIDES, {999: 564}):
            self.assertEqual(match_previous(dict(id=999, name="Nowhere FC"), self.candidates)["id"], 564)


class ValidateNoGames(unittest.TestCase):
    def data(self, prev_k):
        """Two teams; team 2 has no games this season, one match each way unplayed."""
        row = lambda tid, k, ekv, ekt, p: dict(id=tid, name=str(tid), K=k, EKV=ekv, EKT=ekt, P=p)
        t1 = dict(id=1, name="1", players=squad((1, 1200)))
        t2 = dict(id=2, name="2", players=squad((0, 1200)), previous=dict(players=squad((prev_k, 1300))))
        matches = [dict(home=1, away=2, played=True, home_ekv=3, away_ekv=1),
                   dict(home=2, away=1, played=True, home_ekv=1, away_ekv=3)]
        return dict(teams=[t1, t2], matches=matches,
                    standings=[row(1, 2, 6, 2, 4), row(2, 2, 2, 6, 0)])

    def test_passes_when_previous_season_has_games(self):
        validate(self.data(prev_k=5))  # does not raise

    def test_fails_when_neither_season_has_games(self):
        with self.assertRaisesRegex(RuntimeError, "no games played"):
            validate(self.data(prev_k=0))


if __name__ == "__main__":
    unittest.main()
