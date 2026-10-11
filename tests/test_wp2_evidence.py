"""WP2: evidence-check rules on small inline designs (DECISIONS.md D-043 to D-048).

These designs are written here, independently of the preregistered fixture suite.
Each test asserts one rule with values worked by hand. All data are synthetic.
"""
import copy
import json
import unittest
from fractions import Fraction as Q
from pathlib import Path

import designs
from stratum.data import read_table
from stratum.evidence import CODES, check_evidence

ROOT = Path(__file__).resolve().parents[1]


def table(rows, columns):
    lines = [",".join(columns)] + [",".join(str(r.get(c, "")) for c in columns) for r in rows]
    return read_table("inline", text="\n".join(lines) + "\n")


def t2_rows(reps=(4, 4), w=2, s=5, unit=None, wafer_label=None, extra=None):
    """Synthetic T2 rows: runs R1.. (temp low then high), unit deviation pattern."""
    rows, k = [], 0
    for lv, n in zip(("low", "high"), reps):
        for rep in range(n):
            k += 1
            u = unit(lv, rep) if unit else Q(2 * rep - (n - 1), 2)
            for j in range(w):
                for l in range(s):
                    r = {"run": "R%d" % k, "wafer": wafer_label(k, j) if wafer_label else j + 1,
                         "site": l + 1, "temp": lv,
                         "y": float(Q(100) + (4 if lv == "high" else 0) + u)}
                    if extra:
                        r.update(extra(lv, rep, k, j, l))
                    rows.append(r)
    return rows


COLS = ["run", "wafer", "site", "temp", "y"]


def run(decl, rows, cols=COLS):
    return check_evidence(decl, table(rows, cols))


class Vocabulary(unittest.TestCase):
    def test_codes_equal_the_preregistered_vocabulary(self):
        reg = json.loads((ROOT / "fixtures/synthetic_wp2/expectations.json").read_text())
        vocab = {k: (v["severity"], v["stage"]) for k, v in reg["vocabulary"].items()}
        vocab.update({a["code"]: (a["severity"], a["stage"])
                      for a in reg["vocabulary_amendments"]})   # appended post-freeze (D-053)
        self.assertEqual(vocab, CODES)

    def test_checker_never_reads_the_registry(self):
        for name in ("evidence.py", "exact.py", "stats.py", "data.py"):
            text = (ROOT / "stratum" / name).read_text()
            self.assertNotIn("expectations", text)
            self.assertNotIn("synthetic_wp2", text)


class Ownership(unittest.TestCase):
    def test_global_label_under_two_parents(self):
        d = designs.t2()
        d["hierarchy"][1]["id_scope"] = "global"

        def lab(k, j):
            return "W2" if (k, j) == (2, 0) else "W%d" % ((k - 1) * 2 + j + 1)
        res = run(d, t2_rows(wafer_label=lab))
        self.assertEqual(res.categories, ("multiple_parents",))
        self.assertEqual(res.findings[0].details["parents"], ["R1", "R2"])

    def test_parent_scope_label_reuse_is_fine(self):
        # wafer "1" under every run: under id_scope parent these are different wafers.
        self.assertEqual(run(designs.t2(), t2_rows()).decision, "ANALYZE")

    def test_duplicate_identity(self):
        rows = t2_rows()
        rows.append(dict(rows[0]))
        res = run(designs.t2(), rows)
        self.assertEqual(res.categories, ("duplicate_observation",))
        self.assertEqual(res.findings[0].details["lines"], [2, len(rows) + 1])


class Consistency(unittest.TestCase):
    def test_treatment_constant_within_run(self):
        rows = t2_rows()
        for r in rows:
            if r["run"] == "R3" and r["wafer"] == 2:
                r["temp"] = "high"
        res = run(designs.t2(), rows)
        self.assertEqual(res.categories, ("treatment_not_constant",))
        self.assertEqual(res.findings[0].details["units"], {"R3": ["high", "low"]})
        statuses = {s.id: s.status for s in res.stages}
        self.assertEqual(statuses["S4"], "fail")
        self.assertTrue(all(statuses[s] == "not_evaluated" for s in ("S5", "S6", "S7", "S8")))

    def test_missing_column_and_label_and_invalid(self):
        res = run(designs.t2(), t2_rows(), ["run", "wafer", "site", "y"])
        self.assertEqual(res.categories, ("missing_column",))
        rows = t2_rows()
        rows[3]["run"] = "NA"
        rows[4]["y"] = "1/2"          # a fraction is not a decimal number
        rows[5]["y"] = "NA"           # missing, not invalid
        res = run(designs.t2(), rows)
        self.assertEqual(res.categories, ("invalid_response", "missing_label"))


class ReplicationAndBalance(unittest.TestCase):
    def test_actual_r_count(self):
        res = run(designs.t2(), t2_rows(reps=(5, 3)))
        self.assertEqual(res.evidence["replication"]["present_per_level"], {"low": 5, "high": 3})
        self.assertEqual(res.categories, ("unbalanced_units",))

    def test_r_one_with_many_subsamples(self):
        d = designs.t2()
        d["hierarchy"][1]["count_per_parent"] = 10
        rows = t2_rows(reps=(1, 1), w=10, s=5)          # 100 observations, 2 runs
        res = run(d, rows)
        self.assertEqual(res.evidence["replication"]["present_per_level"], {"low": 1, "high": 1})
        self.assertEqual(res.categories, ("insufficient_replication", "missing_top_unit"))

    def test_child_counts(self):
        rows = [r for r in t2_rows() if not (r["run"] == "R2" and r["wafer"] == 2)]
        res = run(designs.t2(), rows)
        self.assertEqual(res.categories, ("missing_intermediate_unit",))
        self.assertEqual(res.findings[0].details["units"], {"R2": 1})
        rows = t2_rows(w=3)
        res = run(designs.t2(), rows)
        self.assertEqual(res.categories, ("count_exceeds_declaration",))


class MissingSites(unittest.TestCase):
    def rows_missing(self, pairs):
        return [r for r in t2_rows() if (r["run"], r["wafer"], r["site"]) not in pairs]

    def test_classification_by_exchangeability(self):
        rows = self.rows_missing({("R2", 1, 3)})
        for exch, code in ((True, "missing_sites_exception"),
                           (False, "missing_sites_not_exchangeable"),
                           (None, "missing_sites_not_exchangeable")):
            with self.subTest(exchangeable=exch):
                d = designs.t2()
                if exch is not None:
                    d["hierarchy"][2]["exchangeable"] = exch
                self.assertEqual(run(d, rows).categories, (code,))

    def test_f_site(self):
        # R2: wafer 1 has 4 of 5, wafer 2 has 5: F_site = (5/2)(1/4 + 1/5) = 9/8.
        d = designs.t2()
        d["hierarchy"][2]["exchangeable"] = True
        res = run(d, self.rows_missing({("R2", 1, 3)}))
        units = res.evidence["missing_sites"]["units"]
        self.assertEqual(units["R2"]["F_site"], Q(9, 8))
        self.assertEqual(units["R1"]["F_site"], 1)
        self.assertEqual(res.decision, "WARN")

    def test_exception_needs_every_higher_unit(self):
        d = designs.t2()
        d["hierarchy"][2]["exchangeable"] = True
        rows = [r for r in self.rows_missing({("R2", 1, 3)}) if r["run"] != "R8"]
        res = run(d, rows)
        self.assertEqual(res.categories, ("missing_top_unit", "unbalanced_units"))
        self.assertFalse(res.evidence["missing_sites"]["exception_applies"])

    def test_positional_labels(self):
        d = designs.t2()
        d["hierarchy"][2]["count_per_parent"] = 4
        rows = [r for r in t2_rows() if r["site"] != (2 if r["run"] == "R1" else 3)]
        self.assertEqual(run(d, rows).categories, ("positional_labels_inconsistent",))
        d["hierarchy"][2]["exchangeable"] = True
        self.assertEqual(run(d, rows).decision, "ANALYZE")


class Confounding(unittest.TestCase):
    def with_chamber(self, assign, role="recorded"):
        d = designs.t2()
        f = {"name": "chamber", "column": "chamber", "recorded_at": "run", "role": role,
             "levels": ["A", "B"]}
        if role == "block":
            f["crossed_with"] = "temp"
        d["nuisance_factors"] = [f]
        rows = t2_rows(extra=lambda lv, rep, k, j, l: {"chamber": assign(lv, rep)})
        return run(d, rows, COLS + ["chamber"])

    def test_complete(self):
        res = self.with_chamber(lambda lv, rep: "A" if lv == "low" else "B")
        self.assertEqual(res.categories, ("complete_confounding",))
        rec = res.evidence["confounding"][0]
        self.assertFalse(rec["contrasts"][0]["estimable"])
        self.assertEqual(rec["cramers_v"], 1.0)

    def test_partial_metrics(self):
        res = self.with_chamber(lambda lv, rep: ("A" if rep < 3 else "B") if lv == "low"
                                else ("A" if rep < 1 else "B"))
        self.assertEqual(res.categories, ("partial_confounding",))
        rec = res.evidence["confounding"][0]
        self.assertEqual(rec["levels"], ["low", "high"])      # declared level order
        self.assertEqual(rec["table"], [[3, 1], [1, 3]])
        self.assertEqual(rec["cramers_v_squared"], Q(1, 4))
        self.assertEqual(rec["contrasts"][0]["variance_ratio"], Q(4, 3))

    def test_balanced_block(self):
        res = self.with_chamber(lambda lv, rep: "A" if rep < 2 else "B", role="block")
        self.assertEqual(res.decision, "ANALYZE")
        self.assertEqual(res.evidence["block_table"]["counts"], [[2, 2], [2, 2]])
        self.assertEqual(res.evidence["confounding"][0]["contrasts"][0]["variance_ratio"], 1)

    def with_day(self, assign):
        d = designs.t2()
        d["nuisance_factors"] = [{"name": "day", "column": "day", "recorded_at": "run",
                                  "role": "recorded"}]
        rows = t2_rows(extra=lambda lv, rep, k, j, l: {"day": assign(lv, rep, k)})
        return run(d, rows, COLS + ["day"])

    def test_unique_day_per_run_warns_not_refuses(self):
        # D-053 A: one day per run renames the runs; it is neither confounding nor aliasing.
        res = self.with_day(lambda lv, rep, k: "2026-03-%02d" % k)
        self.assertEqual(res.decision, "WARN")
        self.assertEqual(res.categories, ("nuisance_unit_unique",))
        self.assertEqual(res.evidence["confounding"][0]["status"], "unit_unique")
        self.assertEqual(res.evidence["aliasing"]["aliased_pairs"], [])
        self.assertEqual(res.evidence["aliasing"]["excluded_unit_unique"], ["day"])

    def test_repeated_day_crossed_with_treatment_is_supported(self):
        res = self.with_day(lambda lv, rep, k: "d1" if rep < 2 else "d2")
        self.assertEqual(res.decision, "ANALYZE")
        self.assertEqual(res.evidence["confounding"][0]["contrasts"][0]["variance_ratio"], 1)

    def test_repeated_day_confounded_with_treatment_refuses(self):
        # D-053 C: shared day levels that coincide with the treatment are still refused.
        res = self.with_day(lambda lv, rep, k: "d1" if lv == "low" else "d2")
        self.assertEqual(res.categories, ("complete_confounding",))

    def test_ordered_drift_variable_reports_trend_evidence(self):
        # Run order 1..8, systematic: low = 1-4, high = 5-8. With a linear trend,
        # Var(high - low)/sigma^2 = 1/4 + 1/4 + (6.5 - 2.5)^2 / Sxx_within, Sxx_within = 2 * 5,
        # = 1/2 + 16/10 = 21/10, against 1/2 alone: variance ratio 21/5.
        res = self.with_day(lambda lv, rep, k: str(k))
        self.assertEqual(res.categories, ("nuisance_unit_unique",))
        trend = res.evidence["confounding"][0]["linear_trend"]
        self.assertTrue(trend["available"])
        self.assertTrue(trend["contrasts"][0]["estimable"])
        self.assertEqual(trend["contrasts"][0]["variance_ratio"], Q(21, 5))
        self.assertIn("21/5", res.findings[0].message)
        # Alternating order (low = 1,3,5,7): mean difference 1, Sxx_within = 2 * 20:
        # 1/2 + 1/40 = 21/40, ratio 21/20.
        res = self.with_day(lambda lv, rep, k: str(2 * rep + (1 if lv == "low" else 2)))
        self.assertEqual(res.evidence["confounding"][0]["linear_trend"]["contrasts"][0]
                         ["variance_ratio"], Q(21, 20))

    def test_unit_unique_below_the_experimental_unit(self):
        # A tool different for every wafer is confined within runs: same rule.
        d = designs.t2()
        d["nuisance_factors"] = [{"name": "tool", "column": "tool", "recorded_at": "wafer",
                                  "role": "recorded"}]
        rows = t2_rows(extra=lambda lv, rep, k, j, l: {"tool": "T%d-%d" % (k, j)})
        res = run(d, rows, COLS + ["tool"])
        self.assertEqual(res.categories, ("nuisance_unit_unique",))
        self.assertFalse(res.evidence["confounding"][0]["linear_trend"]["available"])


class Aliasing(unittest.TestCase):
    def test_partition_equivalence_ignores_labels(self):
        d = designs.t2()
        d["nuisance_factors"] = [
            {"name": "b1", "column": "b1", "recorded_at": "wafer", "role": "recorded"},
            {"name": "b2", "column": "b2", "recorded_at": "wafer", "role": "recorded"}]
        same = lambda lv, rep, k, j, l: {"b1": "K%d" % j, "b2": "Z" if j else "Q"}  # noqa
        res = run(d, t2_rows(extra=same), COLS + ["b1", "b2"])
        self.assertEqual(res.evidence["aliasing"]["aliased_pairs"],
                         [["recorded factor 'b1'", "recorded factor 'b2'"]])
        diff = lambda lv, rep, k, j, l: {"b1": "K%d" % j, "b2": "Z" if (j + k) % 2 else "Q"}  # noqa
        res = run(d, t2_rows(extra=diff), COLS + ["b1", "b2"])
        self.assertEqual(res.evidence["aliasing"]["aliased_pairs"], [])

    def test_w1_warns_in_t2(self):
        # D-054: treatment estimable from replicated runs; run and wafer components aliased.
        d = designs.t2()
        d["hierarchy"][1]["count_per_parent"] = 1
        res = run(d, t2_rows(w=1))
        self.assertEqual(res.categories, ("aliased_components",))
        self.assertEqual(res.decision, "WARN")
        self.assertEqual(res.findings[0].details["unidentified"], ["'run'", "'wafer'"])
        self.assertEqual(res.evidence["replication"]["present_per_level"], {"low": 4, "high": 4})

    def test_s1_warns_in_t2(self):
        d = designs.t2()
        d["hierarchy"][2]["count_per_parent"] = 1
        res = run(d, t2_rows(s=1))
        self.assertEqual(res.decision, "WARN")
        self.assertEqual(res.findings[0].details["unidentified"],
                         ["'wafer'", "'site' (residual)"])

    def test_aliased_lower_level_but_no_replication_refuses(self):
        # The same w = 1 design with one run per level: replication refuses (D-054).
        d = designs.t2()
        d["hierarchy"][1]["count_per_parent"] = 1
        res = run(d, t2_rows(reps=(1, 1), w=1))
        self.assertEqual(res.decision, "REFUSE")
        self.assertIn("insufficient_replication", res.categories)


class Precedence(unittest.TestCase):
    def test_refusal_dominates_and_keeps_every_reason(self):
        d = designs.t2()
        d["hierarchy"][1]["count_per_parent"] = 1
        rows = [r for r in t2_rows(w=1) if r["run"] != "R8"]
        res = run(d, rows)
        self.assertEqual(res.decision, "REFUSE")
        self.assertEqual(res.categories,
                         ("aliased_components", "missing_top_unit", "unbalanced_units"))
        self.assertEqual({s.id: s.status for s in res.stages}["S8"], "not_evaluated")

    def test_notes_do_not_change_the_decision(self):
        d = designs.t2()
        d["hierarchy"][0]["count"] = 4
        d["treatments"][0]["replicates_per_level"] = 2
        res = run(d, t2_rows(reps=(2, 2)))
        self.assertEqual(res.categories, ("diagnostic_unavailable",))
        self.assertEqual(res.decision, "ANALYZE")

    def test_diagnostic_warning_is_not_refusal(self):
        res = run(designs.t2(), t2_rows(unit=lambda lv, rep: Q(2 * rep - 3, 2) *
                                        (8 if lv == "high" else 1)))
        self.assertEqual(res.decision, "WARN")
        self.assertIn("sd_ratio", res.categories)

    def test_wp1_refusal_stops_everything(self):
        d = designs.t2()
        d["treatments"][0]["replicates_per_level"] = 1
        d["hierarchy"][0]["count"] = 2
        res = run(d, t2_rows(reps=(1, 1)))
        self.assertEqual(res.categories, ("declaration_refused",))
        self.assertTrue(res.findings[0].details["wp1_refusals"])

    def test_result_is_json_serializable(self):
        d = designs.t2()
        d["hierarchy"][2]["exchangeable"] = True
        rows = [r for r in t2_rows() if (r["run"], r["site"]) != ("R1", 2)]
        out = json.loads(json.dumps(run(d, rows).to_dict()))
        self.assertEqual(out["decision"], "WARN")
        self.assertEqual(out["evidence"]["missing_sites"]["units"]["R1"]["F_site"]["exact"], "5/4")


class T3Rules(unittest.TestCase):
    def rows(self, drop=(), b_of=None):
        out = []
        for w in range(12):
            for p in range(1, 5):
                if (w, p) in drop:
                    continue
                out.append({"wafer": "W%d" % w, "position": b_of(w, p) if b_of else p,
                            "etch": w // 3 + 1, "y": 6 + w % 3 * 0.5 + p * 0.1 +
                            (0.25 if (w % 3, p) in ((0, 1), (1, 2)) else 0) -
                            (0.25 if (w % 3, p) in ((0, 2), (1, 1)) else 0)})
        return out

    def check(self, rows, decl=None):
        d = decl or designs.t3()
        return check_evidence(d, table(rows, ["wafer", "position", "etch", "y"]))

    def test_valid(self):
        self.assertEqual(self.check(self.rows()).decision, "ANALYZE")

    def test_missing_cells(self):
        res = self.check(self.rows(drop={(0, 2)}))
        self.assertEqual(res.categories, ("missing_subplot_cell",))
        res = self.check(self.rows(drop={(w, 3) for w in range(12)}))
        self.assertEqual(res.categories, ("subplot_level_absent_everywhere",))
        self.assertEqual(res.findings[0].details["remaining"], ["1", "2", "4"])

    def test_reduced_declared(self):
        d = designs.t3()
        d["hierarchy"][1]["count_per_parent"] = 3
        d["treatments"][1]["levels"] = ["1", "2", "4"]
        res = self.check(self.rows(drop={(w, 3) for w in range(12)}), d)
        self.assertEqual(res.decision, "ANALYZE")


if __name__ == "__main__":
    unittest.main()
