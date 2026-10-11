#!/usr/bin/env python3
"""Verify every WP0 reference artifact. Standard library only.

Checks, in order:
  1. every fetched source matches its pinned checksum (manifest.json);
  2. every derived CSV matches its pinned checksum (manifest.json "derived");
  3. every number in reference_numbers.csv is found verbatim in its cited
     source, or (tier r-run) equals the stored R output at the stated precision;
  4. the R outputs reproduce the published/package numbers at the precision
     those sources print (PAIRS below);
  5. the brief's structural claims hold in the files (structure.json);
  6. NIST's furnace table is internally consistent with the balanced E[MS],
     and the handbook's data listing equals FURNACE.DAT;
  7. the missing-site policy derivation checks pass (validation/policy_checks.py).

Usage: python3 reference/verify.py      (after fetch.py and r/run_reference.sh)

Exit status 0 only if every check passes.
"""
import csv
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FETCHED = HERE / "_fetched"
sys.path.insert(0, str(HERE))
import fetch  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((ok, name, detail))


# ---------- helpers ----------

def source_lines(spec):
    """Lines of a fetched file, or of a member of a fetched tarball ("a.tar.gz::member"),
    with whitespace collapsed and blank lines dropped."""
    if "::" in spec:
        tar, member = spec.split("::", 1)
        with tarfile.open(FETCHED / tar) as tf:
            raw = tf.extractfile(member).read()
    else:
        raw = (FETCHED / spec).read_bytes()
    lines = (" ".join(line.split()) for line in raw.decode("latin-1").splitlines())
    return [line for line in lines if line]


def locate(lines, anchor):
    """Index of the line matching the last link of an anchor chain "a||b||c":
    each link is the first line at or after the previous match containing it."""
    i = 0
    for link in anchor.split("||"):
        link = " ".join(link.split())
        while i < len(lines) and link not in lines[i]:
            i += 1
        if i == len(lines):
            return None
    return i


def found_in(lines, start, window, value):
    """Value equals a whole line, or a space-separated token of one (trailing
    prose punctuation stripped), within `window` lines after the anchor."""
    for line in lines[start:start + window + 1]:
        if line == value or value in (t.rstrip(",;:") for t in line.split(" ")):
            return True
    return False


def json_get(obj, path):
    for seg in path.split("/"):
        m = re.fullmatch(r"([^\[]*)(?:\[(.+)\])?", seg)
        key, sel = m.group(1), m.group(2)
        if key:
            obj = obj[key]
        if sel is None:
            continue
        if sel.isdigit():
            obj = obj[int(sel)]
        else:
            conds = dict(c.split("=", 1) for c in sel.split(";"))
            obj = next(r for r in obj if all(str(r.get(k)) == v for k, v in conds.items()))
    return obj


def formats_as(x, value):
    """True if float x, printed at the precision of the string value, equals value."""
    v = value.replace(",", "")
    if "e" in v:
        digits = len(v.split("e")[0].split(".")[1]) if "." in v else 0
        return f"{x:.{digits}e}" == v
    digits = len(v.split(".")[1]) if "." in v else 0
    return f"{x:.{digits}f}" == v


_json_cache = {}


def r_value(rel, path):
    if rel not in _json_cache:
        _json_cache[rel] = json.loads((HERE / rel).read_text())
    return json_get(_json_cache[rel], path)


# ---------- 1-2. checksums ----------

manifest = json.loads((HERE / "manifest.json").read_text())
for entry in manifest["sources"]:
    status = fetch.fetch_entry(entry, offline=True)
    check(f"source checksum {entry['id']}", status.startswith("ok"), status)
for rel, want in manifest.get("derived", {}).items():
    path = FETCHED / rel
    got = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"
    check(f"derived checksum {rel}", got == want, got)

# ---------- 3. every reference number against its source ----------

rows = list(csv.DictReader(open(HERE / "reference_numbers.csv", newline="")))
ids = [r["id"] for r in rows]
check("reference ids unique", len(ids) == len(set(ids)))

# Provenance labeling rules (DECISIONS.md D-013, D-014, D-015).
ROLES = {"canonical", "sensitivity", "cross-check", "optional", "supplementary", "not-obtained"}
for r in rows:
    check(f"{r['id']} role is valid and consistent with tier",
          r["role"] in ROLES and ((r["tier"] == "not-obtained") == (r["role"] == "not-obtained")), r["role"])
    if r["tier"] == "package":
        check(f"{r['id']} package value is labeled as not book-verified",
              "not verified against the book" in r["notes"].lower() or "not the book" in r["notes"].lower())
    if r["tier"] == "not-obtained":
        check(f"{r['id']} unobtained value is left blank", r["value"] == "")
    if r["dataset"] == "oxide" and r["role"] == "canonical":
        check(f"{r['id']} canonical Oxide value comes from a no-Source fit",
              "with_source" not in r["anchor"] and "4.15" not in r["quantity"]
              and "source fixed" not in r["quantity"].lower())
    if r["dataset"] == "lithography":
        check(f"{r['id']} lithography value is optional or supplementary only",
              r["role"] in ("optional", "supplementary"))
by_id = {r["id"]: r for r in rows}
for r in rows:
    name = f"{r['id']} {r['dataset']}: {r['quantity']} = {r['value']}"
    if r["tier"] == "not-obtained":
        check(name + " [NOT OBTAINED - open question]", True, "skipped")
        continue
    if r["tier"] == "r-run":
        try:
            x = r_value(r["source_file"], r["anchor"])
            check(name, formats_as(float(x), r["value"]), f"stored value {x!r}")
        except (KeyError, StopIteration, IndexError, TypeError) as exc:
            check(name, False, f"path not found: {exc!r}")
        continue
    lines = source_lines(r["source_file"])
    at = locate(lines, r["anchor"])
    ok = at is not None and found_in(lines, at, int(r["window"]), r["value"])
    check(name, ok, f"anchor at line {at}" if at is not None else "anchor not found")

# ---------- 4. R outputs reproduce the published / package numbers ----------

PAIRS = [  # (reference id, R output file, JSON path)
    ("F02", "furnace", "aov_error_strata[term=run]/ss"),
    ("F03", "furnace", "aov_error_strata[term=run]/ms"),
    ("F04", "furnace", "f_tests_handbook_form[term=run]/F"),
    ("F07", "furnace", "aov_error_strata[stratum=Error: run:zone]/ss"),
    ("F08", "furnace", "aov_error_strata[stratum=Error: run:zone]/ms"),
    ("F09", "furnace", "f_tests_handbook_form[term=location(run)]/F"),
    ("F10", "furnace", "f_tests_handbook_form[term=location(run)]/p"),
    ("F12", "furnace", "aov_error_strata[stratum=Error: Within]/ss"),
    ("F13", "furnace", "aov_error_strata[stratum=Error: Within]/ms"),
    ("F17", "furnace", "mom_variance_components/run"),
    ("F18", "furnace", "mom_sd/run"),
    ("F19", "furnace", "mom_variance_components/location"),
    ("F20", "furnace", "mom_sd/location"),
    ("F21", "furnace", "mom_variance_components/within"),
    ("F22", "furnace", "mom_sd/within"),
    ("F23", "furnace", "f_tests_handbook_form[term=run]/p"),
    ("L02", "lithography", "aov_error_strata[stratum=Error: cassette]/ss"),
    ("L03", "lithography", "aov_error_strata[stratum=Error: cassette]/ms"),
    ("L04", "lithography", "aov_error_strata[stratum=Error: cassette:wafer]/ss"),
    ("L05", "lithography", "aov_error_strata[stratum=Error: cassette:wafer]/ms"),
    ("L07", "lithography", "aov_error_strata[stratum=Error: Within]/ms"),
    ("L08", "lithography", "mom_variance_components/cassette"),
    ("L09", "lithography", "mom_variance_components/wafer"),
    ("L10", "lithography", "mom_variance_components/wafer"),
    ("L11", "lithography", "mom_variance_components/site"),
    ("L12", "lithography", "nlme_reml/cassette/variance"),
    ("L13", "lithography", "nlme_reml/wafer/variance"),
    ("L14", "lithography", "nlme_reml/Residual/variance"),
    ("F25", "furnace", "nlme_reml/run/variance"),
    ("F26", "furnace", "nlme_reml/zone/variance"),
    ("F27", "furnace", "nlme_reml/Residual/variance"),
    ("O01", "oxide", "without_source/nlme_reml/sd_intervals/Lot/est."),
    ("O02", "oxide", "without_source/nlme_reml/sd_intervals/Wafer/est."),
    ("O03", "oxide", "without_source/nlme_reml/sd_intervals/residual/est."),
    ("O04", "oxide", "without_source/nlme_reml/logLik"),
    ("O05", "oxide", "without_source/nlme_reml/sd_intervals/Lot/lower"),
    ("O06", "oxide", "without_source/nlme_reml/sd_intervals/Lot/upper"),
    ("O07", "oxide", "without_source/nlme_reml/sd_intervals/Wafer/lower"),
    ("O08", "oxide", "without_source/nlme_reml/sd_intervals/Wafer/upper"),
    ("O09", "oxide", "without_source/nlme_reml/sd_intervals/residual/lower"),
    ("O10", "oxide", "without_source/nlme_reml/sd_intervals/residual/upper"),
    ("O11", "oxide", "without_source/lmer_reml/vc/Lot/sd"),
    ("O12", "oxide", "without_source/lmer_reml/vc/Wafer:Lot/sd"),
    ("O13", "oxide", "without_source/lmer_reml/vc/Residual/sd"),
    ("O14", "oxide", "with_source_fixed/nlme_reml_contr_sas/vc/Lot/sd"),
    ("O15", "oxide", "with_source_fixed/nlme_reml_contr_sas/ttable[term=Source1]/Value"),
    ("O16", "oxide", "with_source_fixed/nlme_reml_contr_sas/ttable[term=Source1]/Std.Error"),
    ("O17", "oxide", "with_source_fixed/aov_error_strata[stratum=Error: Lot;term=Residuals]/df"),
    ("O18", "oxide", "with_source_fixed/nlme_reml_contr_sas/ttable[term=Source1]/p.value"),
    ("S01", "semiconductor", "nlme_ml_contr_sas/vc/Grp/sd"),
    ("S02", "semiconductor", "nlme_ml_contr_sas/vc/Residual/sd"),
    ("S03", "semiconductor", "nlme_ml_contr_sas/logLik"),
    ("S04", "semiconductor", "split_plot_aov_error_strata[stratum=Error: Grp;term=Residuals]/df"),
    ("S05", "semiconductor", "split_plot_aov_error_strata[stratum=Error: Within;term=Residuals]/df"),
    ("S07", "semiconductor", "split_plot_aov_error_strata[term=ET]/F"),
    ("S08", "semiconductor", "split_plot_aov_error_strata[term=position]/F"),
    ("S09", "semiconductor", "split_plot_aov_error_strata[term=ET:position]/F"),
    ("S10", "semiconductor", "lmer_reml/vc/Grp/sd"),
    ("S11", "semiconductor", "lmer_reml/vc/Residual/sd"),
]
# Disagreements found when these checks were first run (2026-10-03) and
# explained, not tuned away (DECISIONS.md D-008). Each is still printed on
# every run, and its explanation is itself checked below.
DOCUMENTED_DIFFERENCES = {
    "F26": "NIST's printed nlme REML; iterative optimum differs from current nlme in 3rd decimal",
    "F27": "NIST's printed nlme REML; iterative optimum differs from current nlme in 3rd decimal",
    "L13": "NIST's printed nlme REML; differs from current nlme in the 8th significant digit",
}
differences = []
for ref_id, f, path in PAIRS:
    ref = by_id[ref_id]
    try:
        x = float(r_value(f"r_outputs/{f}.json", path))
    except (KeyError, StopIteration, IndexError, TypeError) as exc:
        check(f"R reproduces {ref_id}", False, f"path not found: {exc!r}")
        continue
    name = f"R reproduces {ref_id} ({ref['quantity']} = {ref['value']})"
    if formats_as(x, ref["value"]):
        check(name, ref_id not in DOCUMENTED_DIFFERENCES,
              "listed as a documented difference but now agrees: update D-008")
    elif ref_id in DOCUMENTED_DIFFERENCES:
        differences.append(f"{ref_id}: published {ref['value']}, R {x:.6g} -- {DOCUMENTED_DIFFERENCES[ref_id]}")
    else:
        check(name, False, f"R value {x!r}")

# The explanation for those differences: with all moment estimates positive in
# a balanced nested design, the exact REML estimate equals the moment estimate,
# so every REML printout should sit within optimizer tolerance of it.
for f, mom_path, reml_paths in (
    ("furnace", "mom_variance_components/location", ["nlme_reml/zone/variance", "lmer_reml/vc/run:zone/variance"]),
    ("furnace", "mom_variance_components/within", ["nlme_reml/Residual/variance", "lmer_reml/vc/Residual/variance"]),
    ("lithography", "mom_variance_components/wafer", ["nlme_reml/wafer/variance", "lmer_reml/vc/wafer:cassette/variance"]),
):
    target = float(r_value(f"r_outputs/{f}.json", mom_path))
    for p in reml_paths:
        x = float(r_value(f"r_outputs/{f}.json", p))
        check(f"{f} REML {p} within 1e-4 relative of moment estimate",
              abs(x - target) <= 1e-4 * abs(target), f"{x!r} vs {target!r}")
for ref_id, mom_path in (("F26", "mom_variance_components/location"), ("F27", "mom_variance_components/within"),
                         ("L13", "mom_variance_components/wafer")):
    f = "lithography" if ref_id.startswith("L") else "furnace"
    target = float(r_value(f"r_outputs/{f}.json", mom_path))
    published = float(by_id[ref_id]["value"])
    check(f"{ref_id} published REML within 1e-4 relative of moment estimate",
          abs(published - target) <= 1e-4 * abs(target), f"{published} vs {target!r}")

# ---------- 5. structural claims in the brief (Section 3.1) ----------

s = json.loads((HERE / "r_outputs" / "structure.json").read_text())


def L(x):
    """jsonlite writes length-1 vectors as scalars; compare as lists."""
    return x if isinstance(x, list) else [x]


claims = [
    ("furnace 168 rows", s["furnace"]["rows"] == 168),
    ("furnace 21 runs x 4 zones x 2 wafers, one reading each",
     len(s["furnace"]["runs"]) == 21 and len(s["furnace"]["zones"]) == 4
     and L(s["furnace"]["obs_per_run_zone"]) == [2] and L(s["furnace"]["obs_per_run_zone_wafer"]) == [1]),
    ("lithography 450 rows", s["lithography"]["rows"] == 450),
    ("lithography 30 cassettes x 3 wafers x 5 sites",
     s["lithography"]["cassettes"] == 30 and len(s["lithography"]["wafers"]) == 3
     and L(s["lithography"]["obs_per_cassette_wafer"]) == [5]),
    ("oxide 72 rows", s["oxide"]["rows"] == 72),
    ("oxide 8 lots x 3 wafers x 3 sites",
     len(s["oxide"]["lots"]) == 8 and L(s["oxide"]["obs_per_lot_wafer"]) == [3]
     and L(s["oxide"]["obs_per_lot_wafer_site"]) == [1]),
    ("oxide two-level Source", len(s["oxide"]["sources"]) == 2),
    ("semiconductor 48 rows", s["semiconductor"]["rows"] == 48),
    ("semiconductor 4 etch times x 3 wafers x 4 positions",
     len(s["semiconductor"]["et_levels"]) == 4 and L(s["semiconductor"]["wafers_per_et"]) == [3]
     and L(s["semiconductor"]["obs_per_grp_position"]) == [1]
     and len(s["semiconductor"]["positions"]) == 4),
    ("no missing values in any dataset",
     all(s[d]["incomplete_rows"] == 0 for d in ("furnace", "lithography", "oxide", "semiconductor"))),
]
for name, ok in claims:
    check(f"brief claim: {name}", ok)

# ---------- 6. NIST furnace internal consistency and data listing ----------

def num(ref_id):
    return float(by_id[ref_id]["value"].replace(",", ""))

a, b, n = 21, 4, 2
check("furnace df: run = a-1, location = a(b-1), within = ab(n-1), total = abn-1",
      (num("F01"), num("F06"), num("F11"), num("F14")) == (a - 1, a * (b - 1), a * b * (n - 1), a * b * n - 1))
# Components recomputed from the published (rounded) mean squares; the page's
# components were computed from unrounded MS, so agreement is to ~1e-3.
vc_run = (num("F03") - num("F08")) / (b * n)
vc_loc = (num("F08") - num("F13")) / n
for ref_id, x in (("F17", vc_run), ("F19", vc_loc), ("F21", num("F13"))):
    check(f"furnace {ref_id} follows from published MS via balanced E[MS]",
          abs(x - num(ref_id)) < 2e-3, f"recomputed {x:.6f} vs published {num(ref_id)}")

page = source_lines("nist/ppc511.txt")
start = locate(page, "RUN ZONE WAFER THICKNESS") + 2
listing = []
for line in page[start:]:
    if not re.fullmatch(r"\d+ \d+ \d+ \d+", line):
        break
    listing.append(tuple(int(t) for t in line.split()))
dat = source_lines("nist/FURNACE.DAT")
dstart = next(i for i, line in enumerate(dat) if re.fullmatch(r"-+", line)) + 1
dat_rows = [tuple(int(t) for t in line.split()) for line in dat[dstart:]]
check("furnace handbook data listing equals FURNACE.DAT (168 rows)",
      listing == dat_rows and len(dat_rows) == 168, f"{len(listing)} listed, {len(dat_rows)} in file")

# ---------- 7. repository-level artifacts ----------

ROOT = HERE.parent
import subprocess  # noqa: E402

proc = subprocess.run([sys.executable, str(ROOT / "validation" / "policy_checks.py")],
                      capture_output=True, text=True)
check("policy derivation checks (validation/policy_checks.py: C-2, C-4)", proc.returncode == 0,
      proc.stdout.strip().splitlines()[-1] if proc.stdout else proc.stderr[-200:])

# ---------- report ----------

failed = [r for r in results if not r[0]]
for ok, name, detail in results:
    if not ok:
        print(f"FAIL  {name}  ({detail})")
print(f"{len(results) - len(failed)}/{len(results)} checks passed"
      + (f", {len(failed)} FAILED" if failed else ""))
for line in differences:
    print("DOCUMENTED DIFFERENCE  " + line)
not_obtained = [r["id"] for r in rows if r["tier"] == "not-obtained"]
if not_obtained:
    print("not obtained (kept blank; package tier is the v1 reference, D-013): " + ", ".join(not_obtained))
sys.exit(1 if failed else 0)
