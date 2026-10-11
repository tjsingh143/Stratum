"""Helpers for the WP4 tests: write small SYNTHETIC designs to files.

WP4 hashes its input files (D-077), so these tests write a declaration and a CSV to a
temporary directory instead of passing in-memory tables. Values come from a fixed linear
congruential sequence, so every design is reproducible; none describes real data.
"""
import copy
import csv
import tempfile
from pathlib import Path

import yaml

import designs


class Lcg:
    def __init__(self, seed=12345):
        self.x = seed

    def __call__(self, spread=20):
        self.x = (1103515245 * self.x + 12345) % (2 ** 31)
        return (self.x % (2 * spread + 1)) - spread       # integer in [-spread, spread]


def t2_declaration(r=3, w=2, s=3, t_levels=("low", "high"), depth=3, block=None,
                   nuisance=None, method="randomized", exchangeable=None, top_count=None):
    d = designs.t2()
    d["hierarchy"][0]["count"] = top_count if top_count is not None else r * len(t_levels)
    d["hierarchy"][1]["count_per_parent"] = w
    if depth == 3:
        d["hierarchy"][2]["count_per_parent"] = s
        if exchangeable is not None:
            d["hierarchy"][2]["exchangeable"] = exchangeable
    else:
        d["hierarchy"] = d["hierarchy"][:2]
    t = d["treatments"][0]
    t["levels"] = list(t_levels)
    t["replicates_per_level"] = r
    t["assignment"] = {"method": method}
    d["comparisons"] = [{"id": "cmp", "kind": "pairwise", "factors": ["temp"],
                         "levels": [t_levels[1], t_levels[0]]}]
    d["nuisance_factors"] = []
    if block:
        d["nuisance_factors"].append({"name": "chamber", "column": "chamber",
                                      "recorded_at": "run", "role": "block",
                                      "levels": list(block), "crossed_with": "temp"})
    if nuisance:
        d["nuisance_factors"].append(copy.deepcopy(nuisance))
    return d


def t2_rows(r=3, w=2, s=3, t_levels=("low", "high"), depth=3, seed=7, effect=30,
            chamber_of=None, extra=None, run_sd=20, wafer_sd=8, site_sd=4):
    """Rows of a balanced T2. chamber_of(level, j) -> chamber label for run j of a level;
    extra(level, j) -> dict of more run-level columns."""
    g = Lcg(seed)
    rows = []
    n = 0
    for li, lv in enumerate(t_levels):
        for j in range(r):
            n += 1
            run = "R%02d" % n
            run_eff = g(run_sd)
            cols = {}
            if chamber_of:
                cols["chamber"] = chamber_of(lv, j)
            if extra:
                cols.update(extra(lv, j))
            for wi in range(1, w + 1):
                wafer_eff = g(wafer_sd)
                sites = range(1, s + 1) if depth == 3 else [None]
                for si in sites:
                    y = 1000 + li * effect + run_eff + wafer_eff + (g(site_sd) if si else 0)
                    row = {"run": run, "wafer": str(wi), "temp": lv, "y": "%.1f" % (y / 10.0)}
                    if si is not None:
                        row["site"] = str(si)
                    row.update(cols)
                    rows.append(row)
    return rows


def write(tmp, decl, rows, name="design_synthetic"):
    tmp = Path(tmp)
    dpath, cpath = tmp / ("%s.yaml" % name), tmp / ("%s.csv" % name)
    dpath.write_text(yaml.safe_dump(decl, sort_keys=False), encoding="utf-8")
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with cpath.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        wr.writerows(rows)
    return dpath, cpath


class TempDirCase:
    """Mixin: self.tmp is a fresh temporary directory per test."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()
