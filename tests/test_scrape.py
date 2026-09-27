import unittest

from bgsim.scrape import parse_program, parse_standings, validate


def standings_page(rows):
    trs = "".join(
        f'<tr><td>{pos}</td><td><a href="x?hold={hid}">{name}</a></td>'
        + "".join(f"<td>{x}</td>" for x in nums) + "</tr>"
        for pos, (hid, name, nums) in enumerate(rows, 1))
    return f"<h2>Stillingen</h2><table>{trs}</table><h2>Topscorere</h2>"


def program_page(home, away, score, boards):
    trs = "".join(
        f"<tr><td>P {hn}<br>{hn}</td><td>{hs}</td><td>-</td><td>{as_}</td><td>Q {an}<br>{an}</td></tr>"
        for hn, hs, as_, an in boards)
    return ('Kampe &#8211; Alle<h5 class="match-collapse-toggle kamphead">søndag d. 27. september 2026 kl. 12:00</h5>'
            f'<div class="match-group kampdesc"><a href="x?hold={home}">H</a><a href="x?hold={away}">A</a>'
            f'<span>{score[0]} &#8211; {score[1]}</span>'
            f'<div class="individual-matches"><table>{trs}</table></div></div>')


class Standings(unittest.TestCase):
    def test_decimal_plus_minus(self):
        # During a match the site shows +/- with a decimal comma.
        rows, names = parse_standings(standings_page([
            (1, "One", [3, 2, 1, 0, 7, 2, 5, "2,5"]),
            (2, "Two", [3, 1, 0, 2, 4, 5, 2, "-0,5"]),
            (3, "Three", [2, 1, 1, 0, 5, 3, 3, 1]),
        ]))
        self.assertEqual(names, {1: "One", 2: "Two", 3: "Three"})
        self.assertEqual((rows[0]["K"], rows[0]["EKV"], rows[0]["P"], rows[0]["pm"]), (3, 7, 5, 2.5))
        self.assertEqual(rows[1]["pm"], -0.5)
        self.assertEqual(rows[2]["pm"], 1)
        self.assertIsInstance(rows[2]["pm"], int)


class Program(unittest.TestCase):
    BOARDS = [(11, 17, 9, 21), (12, 3, 5, 22), (13, 0, 0, 23), (14, 0, 0, 24)]

    def test_in_progress_is_unplayed_with_lineup(self):
        [m] = parse_program(program_page(1, 2, (1, 0), self.BOARDS))
        self.assertFalse(m["played"])
        self.assertEqual(m["in_progress"], dict(home_ekv=1, away_ekv=0))
        self.assertEqual([b["home_dbgfnr"] for b in m["lineup"]], [11, 12, 13, 14])
        self.assertNotIn("home_ekv", m)

    def test_finished_match_is_played(self):
        [m] = parse_program(program_page(1, 2, (3, 1), self.BOARDS))
        self.assertTrue(m["played"])
        self.assertEqual((m["home_ekv"], m["away_ekv"]), (3, 1))
        self.assertNotIn("in_progress", m)

    def test_announced_lineup_without_result(self):
        [m] = parse_program(program_page(1, 2, (0, 0), self.BOARDS))
        self.assertFalse(m["played"])
        self.assertNotIn("in_progress", m)
        self.assertIn("lineup", m)


class Validate(unittest.TestCase):
    def test_counts_partial_score_like_the_site(self):
        team = lambda tid: dict(id=tid, name=str(tid), players=[dict(K=1, rating=1200)])
        row = lambda tid, k, ekv, ekt, p: dict(id=tid, name=str(tid), K=k, EKV=ekv, EKT=ekt, P=p)
        matches = [dict(home=1, away=2, played=False, in_progress=dict(home_ekv=1, away_ekv=0)),
                   dict(home=2, away=1, played=False)]
        data = dict(teams=[team(1), team(2)], matches=matches,
                    standings=[row(1, 1, 1, 0, 2), row(2, 1, 0, 1, 0)])
        validate(data)  # does not raise
        data["standings"][0]["P"] = 1
        with self.assertRaises(RuntimeError):
            validate(data)


if __name__ == "__main__":
    unittest.main()
