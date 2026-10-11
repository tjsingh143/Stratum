"""WP4: the reassignment suggestion for completely confounded T2 designs (brief Section
5.6; DECISIONS.md D-080, D-081).

When a T2 treatment is completely confounded with a categorical nuisance factor recorded at
the experimental unit (a chamber or a day), Stratum refuses the comparison and proposes a
crossed, randomized assignment:

  r' = k * ceil(r / k) units per treatment level, r'/k in every treatment x factor cell,
  randomized within each factor level on a seed derived from the inputs.

The revised declaration is checked by the WP1 matcher (it must match T2 with the factor as
a block) and the planned layout by the exact estimability test of D-045. Its expected
precision under the fitted variance components is SE' = sqrt(2 lambda_U / (r' m)), with
lambda_U the expected mean square of units within treatment x factor cells, estimated from
the confounded data with an exact chi-square interval.
"""
import hashlib
import math
import random
from fractions import Fraction
from typing import List, Optional

from .allocation import (_t2_coefs, bounds, classify, planning_model, plural,
                         point_components)
from .analysis import ALPHA, _contrast_specs
from .dist import chi2_quantile, t_quantile
from .exact import Design, proportional
from .templates import evaluate

Q = Fraction
SEED_PREFIX = "stratum-wp4-reassignment-v1"


def declaration_dict(decl) -> dict:
    """The schema form of a parsed declaration (declarations/README.md)."""
    out = {"stratum_declaration": decl.schema_version,
           "claimed_template": decl.claimed_template}
    if decl.description:
        out["description"] = decl.description
    out["response"] = {"column": decl.response.column, "units": decl.response.units}
    hier = []
    for lv in decl.hierarchy:
        if lv.is_top:
            hier.append({"name": lv.name, "id_column": lv.id_column, "count": lv.count})
        else:
            item = {"name": lv.name, "id_column": lv.id_column, "nested_in": lv.nested_in,
                    "count_per_parent": lv.count, "id_scope": lv.id_scope}
            if lv.exchangeable_declared:
                item["exchangeable"] = lv.exchangeable
            hier.append(item)
    out["hierarchy"] = hier
    out["treatments"] = []
    for t in decl.treatments:
        assignment = {"method": t.assignment_method}
        if t.assignment_description:
            assignment["description"] = t.assignment_description
        out["treatments"].append({"name": t.name, "column": t.column, "levels": list(t.levels),
                                  "applied_to": t.applied_to,
                                  "replicates_per_level": t.replicates_per_level,
                                  "assignment": assignment})
    out["nuisance_factors"] = []
    for f in decl.nuisance_factors:
        item = {"name": f.name, "column": f.column, "recorded_at": f.recorded_at,
                "role": f.role}
        if f.levels is not None:
            item["levels"] = list(f.levels)
        if f.crossed_with is not None:
            item["crossed_with"] = f.crossed_with
        out["nuisance_factors"].append(item)
    out["comparisons"] = []
    for c in decl.comparisons:
        item = {"id": c.id, "kind": c.kind, "factors": list(c.factors)}
        if c.levels is not None:
            item["levels"] = list(c.levels)
        if c.description:
            item["description"] = c.description
        out["comparisons"].append(item)
    if decl.split_plot is not None:
        out["split_plot"] = {"whole_plot_factor": decl.split_plot.whole_plot_factor,
                             "subplot_factor": decl.split_plot.subplot_factor}
    return out


def _seed(decl_sha: str, data_sha: str, factor: str) -> int:
    text = "%s|%s|%s|%s" % (SEED_PREFIX, decl_sha, data_sha, factor)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _fisher_yates(items: List[str], rng: random.Random) -> List[str]:
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = rng.randrange(i + 1)
        out[i], out[j] = out[j], out[i]
    return out


def _confounded_factors(ev):
    """(factor name, [comparison ids]) for complete-confounding findings from the
    categorical rank test, in first-finding order."""
    found = {}
    for f in ev.findings:
        if f.code != "complete_confounding":
            continue
        name = f.details.get("nuisance")
        trend = f.details.get("model") == "linear trend"
        entry = found.setdefault(name, {"comparisons": [], "trend": False})
        entry["trend"] = entry["trend"] or trend
        if f.details.get("comparison") not in entry["comparisons"]:
            entry["comparisons"].append(f.details.get("comparison"))
    return found


def _verify_layout(decl, t, plan_units, block_levels):
    """Exact estimability (D-045) of every declared contrast on the planned unit layout."""
    tl = list(t.levels)
    E, M = len(tl), len(block_levels)
    rows_full = [(0, 1 + tl.index(tr), 1 + E + block_levels.index(b)) for b, tr in plan_units]
    rows_trt = [(0, 1 + tl.index(tr)) for _, tr in plan_units]
    full, trt = Design(rows_full, 1 + E + M), Design(rows_trt, 1 + E)
    table = [[sum(1 for b, tr in plan_units if tr == e and b == n) for n in block_levels]
             for e in tl]
    contrasts = []
    for comp in decl.comparisons:
        for name, coef in _contrast_specs(comp, tl):
            c_trt = [Q(0)] * (1 + E)
            for lv, w in coef.items():
                c_trt[1 + tl.index(lv)] = Q(w)
            q_full, q_trt = full.quad(c_trt + [Q(0)] * M), trt.quad(c_trt)
            contrasts.append({"comparison": comp.id, "contrast": name,
                              "estimable": q_full is not None,
                              "variance_ratio": None if q_full is None else q_full / q_trt})
    ok = (all(c["estimable"] and c["variance_ratio"] == 1 for c in contrasts)
          and proportional(table))
    return {"table": table, "rows": tl, "columns": block_levels, "contrasts": contrasts,
            "proportional": proportional(table), "verified": ok}


def suggestions(ev, decl, decl_sha: str, data_sha: str, plan: Optional[dict]) -> dict:
    """The reassignment section of results.json (D-080)."""
    found = _confounded_factors(ev)
    if not found:
        return {"status": "not_applicable",
                "reason": "no complete confounding was found, so no reassignment is needed"}
    if decl is None or decl.claimed_template != "T2":
        return {"status": "not_produced",
                "reason": "v1 produces reassignment suggestions for confounded T2 assignments "
                          "only (brief Section 4; D-080)",
                "factors": sorted(found)}
    items = []
    for name, info in found.items():
        f = next((x for x in decl.nuisance_factors if x.name == name), None)
        if info["trend"]:
            items.append({"factor": name, "status": "not_produced", "comparisons": info["comparisons"],
                          "reason": "the confounding is with a linear trend in a factor that "
                                    "is unique to each unit; a crossed assignment of such a "
                                    "factor is not defined. Randomize the order of the "
                                    "treatment levels, or record shared periods (D-053 B, "
                                    "D-080)."})
            continue
        if f is None or f.recorded_at != decl.top.name:
            items.append({"factor": name, "status": "not_produced", "comparisons": info["comparisons"],
                          "reason": "the factor is recorded below the experimental unit (%r). "
                                    "The remedy is to balance it inside every %s, which the "
                                    "blocked T2 of D-063 does not model, so v1 states the "
                                    "remedy and does not construct a plan (D-080)."
                                    % (f.recorded_at if f else "?", decl.top.name)})
            continue
        items.append(_one(ev, decl, f, info["comparisons"], decl_sha, data_sha, plan))
    produced = [i for i in items if i["status"] == "produced"]
    return {"status": "produced" if produced else "not_produced", "suggestions": items,
            "note": ("More than one factor is completely confounded. Each suggestion removes "
                     "one; the v1 T2 template allows one block, so the others must also be "
                     "balanced and recorded again." if len(found) > 1 else None)}


def _one(ev, decl, f, comparisons, decl_sha, data_sha, plan) -> dict:
    t = decl.treatments[0]
    ctx = ev.context
    present = {}
    for i in ctx.obs:
        present.setdefault(ctx.ids[i][0], ctx.table.rows[i][f.column])
    observed = set(present.values())
    order = list(f.levels) if f.levels else sorted(observed)
    levels = [lv for lv in order if lv in observed]
    k = len(levels)
    r = t.replicates_per_level
    r_new = k * -(-r // k)
    c = r_new // k
    seed = _seed(decl_sha, data_sha, f.name)
    rng = random.Random(seed)
    plan_rows, plan_units, n = [], [], 0
    for lv in levels:
        order_lv = _fisher_yates([x for x in t.levels for _ in range(c)], rng)
        for slot, tr in enumerate(order_lv, start=1):
            n += 1
            plan_rows.append({"planned_unit": "P%03d" % n, "factor_level": lv, "slot": slot,
                              "treatment": tr})
            plan_units.append((lv, tr))
    revised = declaration_dict(decl)
    revised["description"] = ("Revised design suggested by Stratum (D-080): %s crossed with %s, "
                              "%d %s per treatment level, %d in every cell, randomized within "
                              "each %s level." % (t.name, f.name, r_new, plural(decl.top.name),
                                                  c, f.name))
    revised["hierarchy"][0]["count"] = len(t.levels) * r_new
    tr_rec = revised["treatments"][0]
    tr_rec["replicates_per_level"] = r_new
    tr_rec["assignment"] = {"method": "randomized",
                            "description": "Randomized within each %s level by the "
                                           "reassignment plan (seed %d)." % (f.name, seed)}
    revised["nuisance_factors"] = [{"name": f.name, "column": f.column,
                                    "recorded_at": decl.top.name, "role": "block",
                                    "levels": levels, "crossed_with": t.name}]
    match = evaluate(revised)
    layout = _verify_layout(decl, t, plan_units, levels)
    tcount = len(t.levels)
    df_new = tcount * r_new - tcount - k + 1
    other = [x.name for x in decl.nuisance_factors if x.name != f.name]
    rec = {"factor": f.name, "status": "produced", "comparisons": comparisons,
           "treatment": t.name, "treatment_levels": list(t.levels), "factor_levels": levels,
           "declared_replicates_per_level": r, "replicates_per_level": r_new,
           "extra_units_per_level": r_new - r, "units_per_cell": c,
           "total_units": tcount * r_new, "seed": seed,
           "seed_text": "%s|<declaration sha256>|<data sha256>|%s" % (SEED_PREFIX, f.name),
           "plan": plan_rows,
           "plan_note": "Planned %s are new %s, not relabelled existing ones. Lower levels keep "
                        "their declared counts." % (plural(decl.top.name), plural(decl.top.name)),
           "revised_declaration": revised,
           "revised_match": {"matched": match.matched, "template": match.matched_template,
                             "refusals": [r_.explain() for r_ in match.refusals]},
           "layout_check": layout,
           "estimates": {"contrasts": [x["contrast"] for x in layout["contrasts"]],
                         "error_term": "units within treatment and block (D-063)",
                         "num_df": tcount - 1, "den_df": df_new,
                         "block": "%s level differences, descriptively only" % f.name,
                         "unit_variation": "%s-to-%s variation within a %s level"
                                           % (decl.top.name, decl.top.name, f.name)},
           "removed_factors": other,
           "removed_note": ("Removed from the revised declaration: %s. The v1 T2 template "
                            "allows one block, so they must be recorded again and checked."
                            % ", ".join(other)) if other else None,
           "assumption": "no %s x %s interaction; if one exists, the revised design's "
                         "additive error term is inflated (D-063)" % (t.name, f.name)}
    rec["precision"] = _precision(ev, decl, f, r_new, df_new, plan)
    return rec


def _precision(ev, decl, f, r_new, df_new, plan) -> dict:
    if not plan or not plan.get("eligible"):
        return {"status": "unavailable",
                "reason": "the fitted variance components are not available: %s"
                          % (plan.get("reason") if plan else "no planning evidence")}
    model, info = planning_model(plan["evidence"].context, decl, factor=f)
    comps, lam = point_components(model)
    m = info["m"]
    coefs = _t2_coefs(r_new, info["counts"])
    status = classify(model, coefs)
    lo, hi = bounds(model, coefs, comps)
    out = {"status": status, "label": "planning quantities, not results (D-081)",
           "unit_stratum": {"label": model.level_labels[0], "df": info["unit_df"],
                            "n_cells": info["n_cells"], "n_units": info["n_units"]},
           "m": m, "replicates_per_level": r_new, "error_df": df_new,
           "components": [{"component": model.group_key(g), "label": model.group_label(g),
                           "estimable": g.estimable,
                           "estimate": None if c is None else float(c)}
                          for g, c in zip(model.groups, comps)]}
    if info["unit_df"] == 0:
        out.update(se_lower=math.sqrt(float(lo)), se=None,
                   note="the within-cell unit stratum has 0 degrees of freedom, so only the "
                        "lower-level part is estimable: the standard error is at least this "
                        "value (D-078, D-080)")
        return out
    ms_u = info["unit_ms"]
    nu = info["unit_df"]
    se = math.sqrt(2.0 * float(ms_u) / (r_new * m))
    lam_lo = nu * float(ms_u) / chi2_quantile(1.0 - ALPHA / 2.0, nu)
    lam_hi = nu * float(ms_u) / chi2_quantile(ALPHA / 2.0, nu)
    tq = t_quantile(1.0 - ALPHA / 2.0, float(df_new))
    out.update(lambda_unit=float(ms_u), lambda_unit_df=nu,
               lambda_unit_interval=[lam_lo, lam_hi],
               se=se, se_interval=[math.sqrt(2.0 * lam_lo / (r_new * m)),
                                   math.sqrt(2.0 * lam_hi / (r_new * m))],
               se_interval_method="exact chi-square interval for lambda_U under the model "
                                  "(D-060 item 3, D-080)",
               t_critical=tq, expected_half_width=tq * se,
               se_from_components=math.sqrt(float(lo)) if status == "identified" else None,
               formula="SE' = sqrt(2 lambda_U / (r' m)) = sqrt((2/r') * (sum of components "
                       "divided by the units below them))")
    return out
