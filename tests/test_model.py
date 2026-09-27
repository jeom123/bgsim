import random
import unittest

from bgsim.simulate import ekv_distribution, game_win_prob, mp, poisson_binomial, rank


class RatingFormula(unittest.TestCase):
    def test_dbgf_example(self):
        # backgammon.dk, "Beregning af rating", example 1: 1100 vs 1000, 9 points.
        self.assertAlmostEqual(game_win_prob(1000, 1100, 9), 0.4145, places=4)
        self.assertAlmostEqual(game_win_prob(1100, 1000, 9), 0.5855, places=4)

    def test_equal(self):
        self.assertAlmostEqual(game_win_prob(1200, 1200), 0.5)


class Distributions(unittest.TestCase):
    def test_binomial_matches_poisson_binomial(self):
        a = ekv_distribution(0.6)
        b = poisson_binomial([0.6] * 4)
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y)
        self.assertAlmostEqual(sum(poisson_binomial([0.1, 0.5, 0.7, 0.9])), 1.0)

    def test_mp(self):
        self.assertEqual((mp(3, 1), mp(2, 2), mp(1, 3)), (2, 1, 0))


class Ranking(unittest.TestCase):
    def test_ekv_before_mp(self):
        # § 3.3: EKV first, then MP.
        order = rank([1, 2], {1: 40, 2: 41}, {1: 30, 2: 20}, {}, random.Random(0))
        self.assertEqual(order, [2, 1])

    def test_mp_breaks_ekv_tie(self):
        order = rank([1, 2], {1: 40, 2: 40}, {1: 20, 2: 22}, {}, random.Random(0))
        self.assertEqual(order, [2, 1])

    def test_head_to_head(self):
        h2h = {(1, 2): (5, 3), (2, 1): (3, 1)}
        order = rank([2, 1], {1: 40, 2: 40}, {1: 22, 2: 22}, h2h, random.Random(0))
        self.assertEqual(order, [1, 2])



class Privacy(unittest.TestCase):
    def test_initials(self):
        from bgsim.scrape import initials
        self.assertEqual(initials("Anna-Lisa Example"), "ALE")
        self.assertEqual(initials("Per O. Example"), "POE")
        self.assertIsNone(initials(None))


if __name__ == "__main__":
    unittest.main()
