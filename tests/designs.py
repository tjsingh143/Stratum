"""Hand-written base declarations for the WP1 tests.

These are written out independently of the example files, so the tests do not
depend on the examples being right. Each test deep-copies a base and changes one
thing. All of these are synthetic test declarations; none describes real data.
"""
import copy


def t1():
    return copy.deepcopy({
        "stratum_declaration": 1,
        "claimed_template": "T1",
        "response": {"column": "y", "units": "nm"},
        "hierarchy": [
            {"name": "lot", "id_column": "lot", "count": 6},
            {"name": "wafer", "id_column": "wafer", "nested_in": "lot", "count_per_parent": 3},
            {"name": "site", "id_column": "site", "nested_in": "wafer", "count_per_parent": 4},
        ],
        "treatments": [],
        "nuisance_factors": [],
        "comparisons": [],
    })


def t2():
    return copy.deepcopy({
        "stratum_declaration": 1,
        "claimed_template": "T2",
        "response": {"column": "y", "units": "nm"},
        "hierarchy": [
            {"name": "run", "id_column": "run", "count": 8},
            {"name": "wafer", "id_column": "wafer", "nested_in": "run", "count_per_parent": 2},
            {"name": "site", "id_column": "site", "nested_in": "wafer", "count_per_parent": 5},
        ],
        "treatments": [{
            "name": "temp", "column": "temp", "levels": ["low", "high"],
            "applied_to": "run", "replicates_per_level": 4,
            "assignment": {"method": "randomized"},
        }],
        "nuisance_factors": [],
        "comparisons": [{"id": "high_vs_low", "kind": "pairwise",
                         "factors": ["temp"], "levels": ["high", "low"]}],
    })


def t2_block():
    d = t2()
    d["nuisance_factors"] = [{"name": "chamber", "column": "chamber", "recorded_at": "run",
                              "role": "block", "levels": ["A", "B"], "crossed_with": "temp"}]
    return d


def t3():
    return copy.deepcopy({
        "stratum_declaration": 1,
        "claimed_template": "T3",
        "response": {"column": "y", "units": None},
        "hierarchy": [
            {"name": "wafer", "id_column": "wafer", "count": 12},
            {"name": "position", "id_column": "position", "nested_in": "wafer",
             "count_per_parent": 4},
        ],
        "treatments": [
            {"name": "etch", "column": "etch", "levels": ["1", "2", "3", "4"],
             "applied_to": "wafer", "replicates_per_level": 3,
             "assignment": {"method": "not_stated"}},
            {"name": "pos", "column": "position", "levels": ["1", "2", "3", "4"],
             "applied_to": "position", "replicates_per_level": 12,
             "assignment": {"method": "inherent"}},
        ],
        "nuisance_factors": [],
        "comparisons": [
            {"id": "etch", "kind": "overall", "factors": ["etch"]},
            {"id": "pos", "kind": "overall", "factors": ["pos"]},
            {"id": "etch_x_pos", "kind": "interaction", "factors": ["etch", "pos"]},
        ],
        "split_plot": {"whole_plot_factor": "etch", "subplot_factor": "pos"},
    })
