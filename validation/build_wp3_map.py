#!/usr/bin/env python3
"""Build the frozen WP3 comparison map (DECISIONS.md D-061).

Every one of the rows in reference/reference_numbers.csv is assigned, BEFORE any
Stratum analysis result exists, to one of seven classes:

  EXACT        |stratum - ref| <= 1e-8 * max(1, |ref|)
               a classical closed-form value stored at full precision in r_outputs
  PRINTED      |stratum - ref| <= 0.5 * 10**-d
               a classical closed-form value quoted from a printed page or transcript
               (d = decimal place of the last printed digit)
  ITERATIVE    |stratum - ref| <= max(0.5 * 10**-d, 1e-4 * max(1, |ref|))
               any quantity from a mixed-model / iterative fit (lme4, nlme, lmerTest,
               S-PLUS lme), printed or stored.  The 1e-4 band is D-008's recorded and
               already-verified band for REML printouts against moment estimates.
  STRUCTURAL   exact equality of integers (the published expected-mean-squares equation)
  DESCRIPTIVE  Stratum computes a comparable quantity by a deliberately different method
               (variance-component interval methods); reported side by side, no pass/fail
  OUT_OF_SCOPE no Stratum quantity exists, with the recorded decision that says why
  NOT_OBTAINED a book value that was never obtained (D-005, D-013)

The class follows the reference's PROVENANCE, not convenience: classical aov / pf /
method-of-moments values are EXACT or PRINTED, anything from an iterative mixed-model fit
is ITERATIVE.  ITERATIVE is never tighter than PRINTED.

`target` names a logical path into the analysis result that WP3 produces:
(dataset, kind, key, field).  The dataset keys `oxide_source_kernel` and
`semiconductor_wholeplot_kernel` are the two R-anchored T2 kernel cross-checks of D-067;
they are arithmetic checks of the T2 kernel, not analyses of those datasets as T2
experiments (D-014, D-039).

`extra_checks` holds full-precision comparisons against reference/r_outputs values that
have no row in reference_numbers.csv.  They are frozen here in the same commit.

Standard library only.  Usage:
    python3 validation/build_wp3_map.py            # write the map
    python3 validation/build_wp3_map.py --check     # verify the stored map matches
"""
import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REF_CSV = ROOT / "reference" / "reference_numbers.csv"
R_OUTPUTS = ROOT / "reference" / "r_outputs"
OUT = HERE / "wp3_comparison_map.json"

CLASSES = ("EXACT", "PRINTED", "ITERATIVE", "STRUCTURAL",
           "DESCRIPTIVE", "OUT_OF_SCOPE", "NOT_OBTAINED")
PASS_FAIL = ("EXACT", "PRINTED", "ITERATIVE", "STRUCTURAL")

# Reasons for the three report-only classes, cited to the decision that puts them there.
WHY = {
    "nlme_ci": "nlme's approximate interval for a standard deviation is a different "
               "approximation from Stratum's Satterthwaite and exact intervals (D-060); the "
               "values are shown side by side, with no tolerance.",
    "profile_ci": "lme4's profile-likelihood interval is a different method from Stratum's "
                  "Satterthwaite and exact intervals (D-060); shown side by side, no tolerance.",
    "ml": "a maximum-likelihood fit. Stratum implements REML only (brief Section 5.1, D-064).",
    "fixed_position": "a supplementary fit treating a within-group position as a fixed "
                      "crossed factor. T1 has no fixed factor (D-007, D-015), so Stratum "
                      "computes no comparable quantity.",
    "source_fixed": "the Oxide Source-fixed model. Stratum T1 is not extended to a fixed "
                    "factor and the Source analysis is an external sensitivity reference "
                    "only (D-014); no Stratum declaration matches it (D-039).",
    "not_obtained": "a printed book value that could not be obtained (D-005, D-013).",
}


def t(dataset, kind, key, field):
    return {"dataset": dataset, "kind": kind, "key": key, "field": field}


def J(*path):
    return {"json": list(path)}


PRINTED_REF = {"printed": True}


# ---------------------------------------------------------------------------
# The map: one entry per reference_numbers.csv row id.
#   id -> (class, target or None, ref source, note)
# ---------------------------------------------------------------------------
def entries():
    e = {}

    def add(rid, cls, target=None, ref=PRINTED_REF, note=""):
        assert rid not in e, rid
        e[rid] = (cls, target, ref, note)

    # ---------------- NIST furnace, T1 (A = run, B = zone, residual = wafer) -----------
    pub = [("F01", "A", "df"), ("F02", "A", "ss"), ("F03", "A", "ms"), ("F04", "A", "F"),
           ("F05", "A", "p"), ("F06", "B", "df"), ("F07", "B", "ss"), ("F08", "B", "ms"),
           ("F09", "B", "F"), ("F10", "B", "p"), ("F11", "residual", "df"),
           ("F12", "residual", "ss"), ("F13", "residual", "ms"), ("F14", "total", "df"),
           ("F15", "total", "ss"), ("F16", "total", "ms")]
    for rid, key, field in pub:
        add(rid, "PRINTED", t("furnace", "anova", key, field),
            note="NIST/SEMATECH handbook 3.5.1.4 ANOVA table, reproduced at printed precision")
    for rid, key, field in [("F17", "A", "mom"), ("F18", "A", "sd_mom"),
                            ("F19", "B", "mom"), ("F20", "B", "sd_mom"),
                            ("F21", "residual", "mom"), ("F22", "residual", "sd_mom")]:
        add(rid, "PRINTED", t("furnace", "vc", key, field),
            note="published method-of-moments variance component / SD")
    add("F23", "PRINTED", t("furnace", "anova", "A", "p"),
        note="NIST's own printed R p-value for the run test (classical, not iterative)")
    add("F24", "PRINTED", t("furnace", "anova", "B", "ms"),
        note="NIST's own printed R mean square for location(run)")
    for rid, key in [("F25", "A"), ("F26", "B"), ("F27", "residual")]:
        add(rid, "ITERATIVE", t("furnace", "vc", key, "reml"),
            note="NIST's printed nlme REML component; F26 and F27 are the documented "
                 "differences of D-008")
    add("F28", "STRUCTURAL", t("furnace", "anova", "A", "ems_coefficients"),
        note="published E[MS] equation for the Run stratum: coefficients (8, 2, 1) over "
             "(sigma2_A, sigma2_B, sigma2_residual)")

    add("RF01", "EXACT", t("furnace", "anova", "A", "ms"),
        J("furnace", "aov_error_strata", 0, "ms"))
    add("RF02", "EXACT", t("furnace", "anova", "B", "ms"),
        J("furnace", "aov_error_strata", 1, "ms"))
    add("RF03", "EXACT", t("furnace", "anova", "residual", "ms"),
        J("furnace", "aov_error_strata", 2, "ms"))
    add("RF04", "EXACT", t("furnace", "anova", "A", "F"),
        J("furnace", "f_tests_handbook_form", 0, "F"))
    add("RF05", "EXACT", t("furnace", "anova", "A", "p"),
        J("furnace", "f_tests_handbook_form", 0, "p"))
    add("RF06", "EXACT", t("furnace", "vc", "A", "mom"),
        J("furnace", "mom_variance_components", "run"))
    add("RF07", "EXACT", t("furnace", "vc", "B", "mom"),
        J("furnace", "mom_variance_components", "location"))
    add("RF08", "EXACT", t("furnace", "vc", "residual", "mom"),
        J("furnace", "mom_variance_components", "within"))
    add("RF09", "ITERATIVE", t("furnace", "vc", "A", "reml"),
        J("furnace", "lmer_reml", "vc", "run", "variance"))
    add("RF10", "ITERATIVE", t("furnace", "vc", "B", "reml"),
        J("furnace", "lmer_reml", "vc", "run:zone", "variance"))
    add("RF11", "ITERATIVE", t("furnace", "vc", "residual", "reml"),
        J("furnace", "lmer_reml", "vc", "Residual", "variance"))
    add("RF12", "ITERATIVE", t("furnace", "vc", "A", "reml"),
        J("furnace", "nlme_reml", "run", "variance"))
    add("RF13", "ITERATIVE", t("furnace", "vc", "B", "reml"),
        J("furnace", "nlme_reml", "zone", "variance"))
    add("RF14", "DESCRIPTIVE", t("furnace", "vc", "A", "sd_interval_lower"),
        J("furnace", "lmer_reml", "profile_sd_ci", 1, "lower"), WHY["profile_ci"])
    add("RF15", "DESCRIPTIVE", t("furnace", "vc", "A", "sd_interval_upper"),
        J("furnace", "lmer_reml", "profile_sd_ci", 1, "upper"), WHY["profile_ci"])
    add("RF16", "OUT_OF_SCOPE", None, PRINTED_REF, WHY["fixed_position"])
    add("RF17", "OUT_OF_SCOPE", None, PRINTED_REF, WHY["fixed_position"])

    # ---------------- MEMSS Oxide, T1 without Source (A = lot, B = wafer) -------------
    for rid, key in [("O01", "A"), ("O02", "B"), ("O03", "residual"),
                     ("O11", "A"), ("O12", "B"), ("O13", "residual")]:
        add(rid, "ITERATIVE", t("oxide", "vc", key, "sd_reml"),
            note="printed REML SD (nlme re-run / S-PLUS transcript of the no-Source model)")
    add("O04", "ITERATIVE", t("oxide", "reml", "fit", "restricted_loglik"),
        note="nlme printed restricted log-likelihood")
    for rid, key, side in [("O05", "A", "lower"), ("O06", "A", "upper"),
                           ("O07", "B", "lower"), ("O08", "B", "upper"),
                           ("O09", "residual", "lower"), ("O10", "residual", "upper")]:
        add(rid, "DESCRIPTIVE", t("oxide", "vc", key, "sd_interval_" + side),
            PRINTED_REF, WHY["nlme_ci"])
    # Oxide Source rows: used only as the T2 kernel arithmetic cross-check (D-067).
    add("O14", "ITERATIVE", t("oxide_source_kernel", "vc", "unit", "sd_reml"),
        note="T2 kernel cross-check only (D-067); not an analysis of Oxide as T2")
    add("O15", "ITERATIVE", t("oxide_source_kernel", "estimate", "contrast", "estimate"),
        note="T2 kernel cross-check only (D-067)")
    add("O16", "ITERATIVE", t("oxide_source_kernel", "estimate", "contrast", "se"),
        note="T2 kernel cross-check only (D-067)")
    add("O17", "ITERATIVE", t("oxide_source_kernel", "estimate", "contrast", "df"),
        note="T2 kernel cross-check only (D-067)")
    add("O18", "ITERATIVE", t("oxide_source_kernel", "estimate", "contrast", "p"),
        note="T2 kernel cross-check only (D-067)")
    add("O19", "NOT_OBTAINED", None, PRINTED_REF, WHY["not_obtained"])
    add("O20", "NOT_OBTAINED", None, PRINTED_REF, WHY["not_obtained"])

    base = ("oxide", "without_source")
    add("RO01", "EXACT", t("oxide", "anova", "A", "ms"),
        J(*base, "aov_error_strata", 0, "ms"))
    add("RO02", "EXACT", t("oxide", "anova", "B", "ms"),
        J(*base, "aov_error_strata", 1, "ms"))
    add("RO03", "EXACT", t("oxide", "anova", "residual", "ms"),
        J(*base, "aov_error_strata", 2, "ms"))
    add("RO04", "EXACT", t("oxide", "vc", "A", "mom"),
        J(*base, "mom_variance_components", "lot"))
    add("RO05", "EXACT", t("oxide", "vc", "B", "mom"),
        J(*base, "mom_variance_components", "wafer"))
    add("RO06", "EXACT", t("oxide", "vc", "residual", "mom"),
        J(*base, "mom_variance_components", "site"))
    add("RO07", "ITERATIVE", t("oxide", "vc", "A", "sd_reml"),
        J(*base, "lmer_reml", "vc", "Lot", "sd"))
    add("RO08", "ITERATIVE", t("oxide", "vc", "B", "sd_reml"),
        J(*base, "lmer_reml", "vc", "Wafer:Lot", "sd"))
    add("RO09", "ITERATIVE", t("oxide", "vc", "residual", "sd_reml"),
        J(*base, "lmer_reml", "vc", "Residual", "sd"))
    add("RO10", "DESCRIPTIVE", t("oxide", "vc", "A", "sd_interval_lower"),
        J(*base, "nlme_reml", "sd_intervals", "Lot", "lower"), WHY["nlme_ci"])
    add("RO11", "DESCRIPTIVE", t("oxide", "vc", "A", "sd_interval_upper"),
        J(*base, "nlme_reml", "sd_intervals", "Lot", "upper"), WHY["nlme_ci"])
    src = ("oxide", "with_source_fixed")
    add("RO12", "EXACT", t("oxide_source_kernel", "anova", "treatment", "F"),
        J(*src, "aov_error_strata", 0, "F"),
        "T2 kernel cross-check only (D-067); classical aov Error-strata F")
    add("RO13", "EXACT", t("oxide_source_kernel", "anova", "treatment", "p"),
        J(*src, "aov_error_strata", 0, "p"), "T2 kernel cross-check only (D-067)")
    add("RO14", "ITERATIVE", t("oxide_source_kernel", "estimate", "contrast", "df"),
        J(*src, "lmertest_type3_satterthwaite", 0, "den_df"),
        "T2 kernel cross-check only (D-067); Satterthwaite denominator df")
    add("RO15", "ITERATIVE", t("oxide_source_kernel", "anova", "treatment", "p"),
        J(*src, "lmertest_type3_kenward_roger", 0, "p"),
        "T2 kernel cross-check only (D-067); Kenward-Roger p")
    add("RO16", "ITERATIVE", t("oxide_source_kernel", "estimate", "contrast", "estimate"),
        J(*src, "nlme_reml_contr_sas", "ttable", 1, "Value"),
        "T2 kernel cross-check only (D-067)")
    add("RO17", "ITERATIVE", t("oxide_source_kernel", "estimate", "contrast", "se"),
        J(*src, "nlme_reml_contr_sas", "ttable", 1, "Std.Error"),
        "T2 kernel cross-check only (D-067)")
    add("RO18", "ITERATIVE", t("oxide_source_kernel", "vc", "unit", "sd_reml"),
        J(*src, "lmer_reml", "vc", "Lot", "sd"), "T2 kernel cross-check only (D-067)")

    # ---------------- SASmixed Semiconductor, T3 --------------------------------------
    for rid, key, field in [("S04", "A", "den_df"), ("S05", "B", "den_df")]:
        add(rid, "ITERATIVE", t("semiconductor", "anova", key, field),
            note="denominator df printed in the S-PLUS ML transcript's t-table")
    for rid in ("S01", "S02", "S03"):
        add(rid, "OUT_OF_SCOPE", None, PRINTED_REF, WHY["ml"])
    add("S06", "NOT_OBTAINED", None, PRINTED_REF, WHY["not_obtained"])
    for rid, key in [("S07", "A"), ("S08", "B"), ("S09", "AB")]:
        add(rid, "ITERATIVE", t("semiconductor", "anova", key, "F"),
            note="third-party rendering of the package lmer example's ANOVA (D-020)")
    add("S10", "ITERATIVE", t("semiconductor", "vc", "wholeplot", "sd_reml"),
        note="third-party rendering of the package lmer example (D-020)")
    add("S11", "ITERATIVE", t("semiconductor", "vc", "residual", "sd_reml"),
        note="third-party rendering of the package lmer example (D-020)")

    sp = ("semiconductor", "split_plot_aov_error_strata")
    for rid, idx, key, field in [
            ("RS01", 0, "A", "F"), ("RS02", 0, "A", "p"), ("RS03", 0, "A", "df"),
            ("RS04", 1, "wholeplot_error", "df"), ("RS05", 1, "wholeplot_error", "ms"),
            ("RS06", 2, "B", "F"), ("RS07", 2, "B", "p"),
            ("RS08", 3, "AB", "F"), ("RS09", 3, "AB", "p"),
            ("RS10", 4, "subplot_error", "df"), ("RS11", 4, "subplot_error", "ms")]:
        add(rid, "EXACT", t("semiconductor", "anova", key, field), J(*sp, idx, field))
    add("RS12", "EXACT", t("semiconductor", "naive_anova", "A", "F"),
        J("semiconductor", "naive_aov", 0, "F"))
    add("RS13", "EXACT", t("semiconductor", "naive_anova", "A", "p"),
        J("semiconductor", "naive_aov", 0, "p"))
    add("RS14", "EXACT", t("semiconductor", "naive_anova", "residual", "df"),
        J("semiconductor", "naive_aov", 3, "df"))
    add("RS15", "ITERATIVE", t("semiconductor", "anova", "A", "den_df"),
        J("semiconductor", "lmertest_type3_satterthwaite", 0, "den_df"))
    add("RS16", "ITERATIVE", t("semiconductor", "anova", "B", "den_df"),
        J("semiconductor", "lmertest_type3_kenward_roger", 1, "den_df"))
    add("RS17", "ITERATIVE", t("semiconductor", "vc", "wholeplot", "reml"),
        J("semiconductor", "lmer_reml", "vc", "Grp", "variance"))
    add("RS18", "ITERATIVE", t("semiconductor", "vc", "residual", "reml"),
        J("semiconductor", "lmer_reml", "vc", "Residual", "variance"))
    add("RS19", "OUT_OF_SCOPE", None, PRINTED_REF, WHY["ml"])
    add("RS20", "OUT_OF_SCOPE", None, PRINTED_REF, WHY["ml"])

    # ---------------- NIST lithography, T1, optional (D-015) --------------------------
    for rid, key, field in [("L01", "A", "df"), ("L02", "A", "ss"), ("L03", "A", "ms"),
                            ("L04", "B", "ss"), ("L05", "B", "ms"),
                            ("L06", "residual", "df"), ("L07", "residual", "ms")]:
        add(rid, "PRINTED", t("lithography", "anova", key, field),
            note="NIST/SEMATECH handbook 6.6.1.3 nested ANOVA table")
    for rid, key in [("L08", "A"), ("L09", "B"), ("L10", "B"), ("L11", "residual")]:
        add(rid, "PRINTED", t("lithography", "vc", key, "mom"),
            note="published method-of-moments component (L09 table / L10 text, D-008)")
    for rid, key in [("L12", "A"), ("L13", "B"), ("L14", "residual")]:
        add(rid, "ITERATIVE", t("lithography", "vc", key, "reml"),
            note="NIST's printed nlme REML component; L13 is a documented difference (D-008)")
    for rid, idx, key in [("RL01", 0, "A"), ("RL02", 1, "B"), ("RL03", 2, "residual")]:
        add(rid, "EXACT", t("lithography", "anova", key, "ms"),
            J("lithography", "aov_error_strata", idx, "ms"))
    for rid, key, name in [("RL04", "A", "cassette"), ("RL05", "B", "wafer"),
                           ("RL06", "residual", "site")]:
        add(rid, "EXACT", t("lithography", "vc", key, "mom"),
            J("lithography", "mom_variance_components", name))
    add("RL07", "OUT_OF_SCOPE", None, PRINTED_REF, WHY["fixed_position"])
    add("RL08", "OUT_OF_SCOPE", None, PRINTED_REF, WHY["fixed_position"])
    return e


# ---------------------------------------------------------------------------
# Extra full-precision checks with no reference_numbers.csv row (frozen here too).
# ---------------------------------------------------------------------------
def extra_checks():
    x = []

    def add(cls, target, ref, note=""):
        x.append({"class": cls, "target": target, "ref": ref, "note": note})

    # furnace
    for idx, key in [(0, "A"), (1, "B"), (2, "residual")]:
        add("EXACT", t("furnace", "anova", key, "ss"),
            J("furnace", "aov_error_strata", idx, "ss"))
        add("EXACT", t("furnace", "anova", key, "df"),
            J("furnace", "aov_error_strata", idx, "df"))
    add("EXACT", t("furnace", "anova", "B", "F"), J("furnace", "f_tests_handbook_form", 1, "F"))
    add("EXACT", t("furnace", "anova", "B", "p"), J("furnace", "f_tests_handbook_form", 1, "p"))
    for key, name in [("A", "run"), ("B", "location"), ("residual", "within")]:
        add("EXACT", t("furnace", "vc", key, "sd_mom"), J("furnace", "mom_sd", name))
        add("EXACT", t("furnace", "vc", key, "percent_of_total"),
            J("furnace", "mom_percent_of_total", name))
    add("EXACT", t("furnace", "estimate", "grand_mean", "estimate"),
        J("furnace", "lmer_reml", "intercept"),
        "for a balanced design the REML intercept is the grand mean exactly")
    for key, name in [("A", "run"), ("B", "run:zone"), ("residual", "Residual")]:
        add("ITERATIVE", t("furnace", "vc", key, "sd_reml"),
            J("furnace", "lmer_reml", "vc", name, "sd"))

    # oxide (no-Source model)
    base = ("oxide", "without_source")
    for idx, key in [(0, "A"), (1, "B"), (2, "residual")]:
        add("EXACT", t("oxide", "anova", key, "ss"), J(*base, "aov_error_strata", idx, "ss"))
        add("EXACT", t("oxide", "anova", key, "df"), J(*base, "aov_error_strata", idx, "df"))
    for key, name in [("A", "lot"), ("B", "wafer"), ("residual", "site")]:
        add("EXACT", t("oxide", "vc", key, "sd_mom"), J(*base, "mom_sd", name))
    add("EXACT", t("oxide", "estimate", "grand_mean", "estimate"),
        J(*base, "lmer_reml", "intercept"))
    add("ITERATIVE", t("oxide", "reml", "fit", "restricted_loglik"),
        J(*base, "nlme_reml", "logLik"))
    for key, name in [("A", "Lot"), ("B", "Wafer"), ("residual", "Residual")]:
        add("ITERATIVE", t("oxide", "vc", key, "reml"),
            J(*base, "nlme_reml", "vc", name, "variance"))

    # semiconductor: every split-plot and naive row, in full
    for idx, key in [(0, "A"), (1, "wholeplot_error"), (2, "B"), (3, "AB"),
                     (4, "subplot_error")]:
        for field in ("df", "ss", "ms"):
            add("EXACT", t("semiconductor", "anova", key, field),
                J("semiconductor", "split_plot_aov_error_strata", idx, field))
    for idx, key in [(0, "A"), (1, "B"), (2, "AB"), (3, "residual")]:
        for field in ("df", "ss", "ms"):
            add("EXACT", t("semiconductor", "naive_anova", key, field),
                J("semiconductor", "naive_aov", idx, field))
    for idx, key in [(1, "B"), (2, "AB")]:
        add("EXACT", t("semiconductor", "naive_anova", key, "F"),
            J("semiconductor", "naive_aov", idx, "F"))
        add("EXACT", t("semiconductor", "naive_anova", key, "p"),
            J("semiconductor", "naive_aov", idx, "p"))
    for key, name in [("wholeplot", "Grp"), ("residual", "Residual")]:
        add("ITERATIVE", t("semiconductor", "vc", key, "sd_reml"),
            J("semiconductor", "lmer_reml", "vc", name, "sd"))
    add("ITERATIVE", t("semiconductor", "reml", "fit", "minus2_restricted_loglik"),
        J("semiconductor", "lmer_reml", "reml_criterion"),
        "lme4's REMLcrit is -2 x the restricted log-likelihood; the convention is named, "
        "and any constant offset is reported rather than absorbed")
    for idx, key in [(0, "A"), (1, "B"), (2, "AB")]:
        for field in ("F", "p"):
            add("ITERATIVE", t("semiconductor", "anova", key, field),
                J("semiconductor", "lmertest_type3_satterthwaite", idx, field))
    add("ITERATIVE", t("semiconductor", "anova", "AB", "den_df"),
        J("semiconductor", "lmertest_type3_kenward_roger", 2, "den_df"))

    # lithography
    for idx, key in [(0, "A"), (1, "B"), (2, "residual")]:
        add("EXACT", t("lithography", "anova", key, "ss"),
            J("lithography", "aov_error_strata", idx, "ss"))
        add("EXACT", t("lithography", "anova", key, "df"),
            J("lithography", "aov_error_strata", idx, "df"))
    for key, name in [("A", "cassette"), ("B", "wafer"), ("residual", "Residual")]:
        add("ITERATIVE", t("lithography", "vc", key, "reml"),
            J("lithography", "nlme_reml", name, "variance"))

    # the second T2 kernel cross-check (D-067): the Semiconductor whole-plot stratum is
    # exactly b x the one-way analysis of the 12 wafer means.
    add("EXACT", t("semiconductor_wholeplot_kernel", "anova", "treatment", "F"),
        J("semiconductor", "split_plot_aov_error_strata", 0, "F"),
        "T2 kernel cross-check only (D-067)")
    add("EXACT", t("semiconductor_wholeplot_kernel", "anova", "treatment", "p"),
        J("semiconductor", "split_plot_aov_error_strata", 0, "p"),
        "T2 kernel cross-check only (D-067)")
    add("EXACT", t("semiconductor_wholeplot_kernel", "anova", "treatment", "den_df"),
        J("semiconductor", "split_plot_aov_error_strata", 1, "df"),
        "T2 kernel cross-check only (D-067)")
    return x


def decimal_place(text):
    """The decimal place of the last digit printed, after stripping thousands separators.
    '571.659' -> 3, '10,155' -> 0, '3.85e-11' -> 13, '0.0000001' -> 7."""
    s = text.strip().replace(",", "").lstrip("+-")
    if not s:
        return None
    try:
        float(s)
    except ValueError:
        return None          # not a number (F28 is a published E[MS] equation)
    exp = 0
    for marker in ("e", "E"):
        if marker in s:
            s, _, tail = s.partition(marker)
            exp = int(tail)
            break
    frac = len(s.split(".")[1]) if "." in s else 0
    return frac - exp


def resolve(obj, path):
    for step in path:
        obj = obj[step]
    return obj


def build():
    with REF_CSV.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    table = entries()
    ids = [r["id"] for r in rows]
    missing = sorted(set(ids) - set(table))
    extra = sorted(set(table) - set(ids))
    if missing or extra:
        raise SystemExit("map/CSV mismatch: missing %s, unknown %s" % (missing, extra))
    loaded = {}
    out = []
    for r in rows:
        cls, target, ref, note = table[r["id"]]
        if cls not in CLASSES:
            raise SystemExit("unknown class %r for %s" % (cls, r["id"]))
        if (target is None) != (cls in ("OUT_OF_SCOPE", "NOT_OBTAINED")):
            raise SystemExit("%s: class %s and target %r disagree" % (r["id"], cls, target))
        item = {"id": r["id"], "dataset": r["dataset"], "quantity": r["quantity"],
                "tier": r["tier"], "role": r["role"], "printed_value": r["value"],
                "class": cls, "target": target, "note": note}
        if cls not in ("OUT_OF_SCOPE", "NOT_OBTAINED"):
            item["printed_decimal_place"] = decimal_place(r["value"])
        if "json" in ref:
            stem = ref["json"][0]
            if stem not in loaded:
                loaded[stem] = json.loads((R_OUTPUTS / (stem + ".json")).read_text())
            item["ref"] = {"source": "r_outputs", "path": ref["json"],
                           "value": resolve(loaded[stem], ref["json"][1:])}
        else:
            item["ref"] = {"source": "printed", "value": r["value"]}
        out.append(item)

    xs = []
    for item in extra_checks():
        stem = item["ref"]["json"][0]
        if stem not in loaded:
            loaded[stem] = json.loads((R_OUTPUTS / (stem + ".json")).read_text())
        xs.append({"class": item["class"], "target": item["target"], "note": item["note"],
                   "ref": {"source": "r_outputs", "path": item["ref"]["json"],
                           "value": resolve(loaded[stem], item["ref"]["json"][1:])}})

    counts = {}
    for item in out:
        counts[item["class"]] = counts.get(item["class"], 0) + 1
    return {
        "description": "Frozen WP3 comparison map (DECISIONS.md D-061). Every row of "
                       "reference/reference_numbers.csv is classified before any Stratum "
                       "analysis result exists.",
        "frozen_by": "D-061",
        "classes": {
            "EXACT": "|stratum - ref| <= 1e-8 * max(1, |ref|)",
            "PRINTED": "|stratum - ref| <= 0.5 * 10**-printed_decimal_place",
            "ITERATIVE": "|stratum - ref| <= max(0.5 * 10**-printed_decimal_place, "
                         "1e-4 * max(1, |ref|))",
            "STRUCTURAL": "exact equality of integer coefficients",
            "DESCRIPTIVE": "reported side by side; no tolerance (different method by design)",
            "OUT_OF_SCOPE": "no Stratum quantity exists; the reason names the decision",
            "NOT_OBTAINED": "book value never obtained (D-005, D-013)",
        },
        "pass_fail_classes": list(PASS_FAIL),
        "rows": len(out),
        "class_counts": counts,
        "reference_rows": out,
        "extra_checks": xs,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify the stored map matches")
    args = ap.parse_args()
    built = build()
    text = json.dumps(built, indent=2, sort_keys=False) + "\n"
    if args.check:
        if not OUT.exists():
            print("MISSING %s" % OUT.name)
            return 1
        if OUT.read_text() != text:
            print("MISMATCH: %s differs from the generator" % OUT.name)
            return 1
        print("wp3 comparison map matches generator: %d reference rows, %d extra checks"
              % (built["rows"], len(built["extra_checks"])))
        return 0
    OUT.write_text(text)
    print("wrote %s: %d reference rows, %d extra checks" % (OUT.name, built["rows"],
                                                            len(built["extra_checks"])))
    for cls in CLASSES:
        print("  %-13s %d" % (cls, built["class_counts"].get(cls, 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
