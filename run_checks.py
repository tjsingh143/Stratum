#!/usr/bin/env python3
"""Run the verification checks that this repository supports, and summarize them.

    python3 run_checks.py                  # uses .venv/bin/python when it exists
    python3 run_checks.py --python PATH    # any interpreter with PyYAML 6.0.3 installed

Checks that need the published reference data are reported as SKIPPED when
reference/_fetched/ is absent; a skipped check is never counted as passed. The data
are fetched and checksum-verified rather than redistributed; see reference/README.md
(`python3 reference/fetch.py`, then `python3 reference/replay.py`, which needs Docker).

Not run here: the pinned Docker/R replay itself (`python3 reference/replay.py`) and
anything that needs material outside this repository (see REPRODUCIBILITY.md).

Exit status: 0 if no check failed, 1 if any check failed, 2 if the environment is unusable.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FETCHED = ROOT / "reference" / "_fetched"

# (label, command after the interpreter, needs the fetched reference data)
CHECKS = [
    ("unit tests", ["-m", "unittest", "discover", "-s", "tests", "-t", "tests", "-q"], False),
    ("synthetic fixtures regenerate", ["fixtures/synthetic_wp2/generate.py", "--check"], False),
    ("fixture registry is well formed", ["fixtures/synthetic_wp2/validate_registry.py"], False),
    ("explanation registry and guide", ["-m", "stratum", "explanations", "--check"], False),
    ("scenario inputs regenerate", ["scenarios/generate.py", "--check"], False),
    ("scenario outputs and assertions", ["scenarios/run.py", "--all", "--check"], False),
    ("WP3 comparison map regenerates", ["validation/build_wp3_map.py", "--check"], False),
    ("missing-site policy derivations", ["validation/policy_checks.py"], False),
    ("reference sources match pinned checksums", ["reference/fetch.py", "--offline"], True),
    ("reference numbers and R outputs", ["reference/verify.py"], True),
    ("fixture comparison table", ["fixtures/synthetic_wp2/run_fixtures.py", "--check"], True),
    ("WP3 published reproduction", ["validation/wp3_reproduce.py", "--check"], True),
    ("committed reports regenerate", ["reports/generate.py", "--check"], True),
]


def reference_data_present() -> bool:
    try:
        manifest = json.loads((ROOT / "reference" / "manifest.json").read_text())
    except (OSError, ValueError):
        return False
    paths = [FETCHED / item["id"] for item in manifest.get("sources", [])]
    paths += [FETCHED / rel for rel in manifest.get("derived", {})]
    return bool(paths) and all(p.is_file() for p in paths)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--python", default=None, help="interpreter used for every check")
    ap.add_argument("--verbose", action="store_true", help="print the output of every check")
    args = ap.parse_args()
    venv = ROOT / ".venv" / "bin" / "python"
    python = args.python or (str(venv) if venv.exists() else sys.executable)
    probe = subprocess.run([python, "-c", "import yaml, sys; print(yaml.__version__, sys.version.split()[0])"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        print("error: %s cannot import PyYAML; run: python3 -m venv .venv && "
              ".venv/bin/python -m pip install -r requirements.txt" % python, file=sys.stderr)
        return 2
    pyyaml, version = probe.stdout.split()
    have_data = reference_data_present()
    print("Python %s, PyYAML %s; reference data %s" % (version, pyyaml,
          "present" if have_data else "absent (data-dependent checks are skipped)"))
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    results = []
    for label, cmd, needs_data in CHECKS:
        if needs_data and not have_data:
            results.append((label, "SKIPPED", "needs reference/_fetched/ (see reference/README.md)"))
            continue
        t0 = time.time()
        proc = subprocess.run([python] + cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        output = (proc.stdout + proc.stderr).strip()
        status = "PASS" if proc.returncode == 0 else "FAIL (exit %d)" % proc.returncode
        last = output.splitlines()[-1] if output else ""
        results.append((label, status, "%.1fs; %s" % (time.time() - t0, last[:110])))
        if args.verbose or proc.returncode != 0:
            print("--- %s: %s\n%s" % (label, " ".join(cmd), output))
    width = max(len(r[0]) for r in results)
    for label, status, note in results:
        print("%-*s  %-14s %s" % (width, label, status, note))
    failed = [r for r in results if r[1].startswith("FAIL")]
    skipped = [r for r in results if r[1] == "SKIPPED"]
    print("%d passed, %d failed, %d skipped" % (len(results) - len(failed) - len(skipped),
                                               len(failed), len(skipped)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
