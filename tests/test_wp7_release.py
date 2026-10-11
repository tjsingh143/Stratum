"""WP7 regression checks: input integrity, singular data and CLI."""
import contextlib
import csv
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from stratum.analysis import analyze
from stratum.cli import main
from stratum.data import Table, read_table
from stratum.report import render
from stratum.results import build, dumps
from validation.wp6_generate import declaration, generate
import wp4_helpers as H

ROOT = Path(__file__).resolve().parents[1]
M = json.loads((ROOT / 'tests/data/wp6_conforming_cells.json').read_text())


class Degenerate(unittest.TestCase):
    def check_case(self, group, transform):
        c = M['cells'][group][0]
        rows = generate(c, random.Random(c['seed']), M['adverse_parameters'], M['non_null_effects'])
        for row in rows:
            row['y'] = str(transform(row))
        with tempfile.TemporaryDirectory(prefix='stratum-test-') as tmp:
            dp, cp = H.write(tmp, declaration(c), rows)
            doc = build(dp, cp)
            json.loads(dumps(doc))  # strict JSON: neither NaN nor infinity
            text = render(doc)
        self.assertTrue(doc['analysis']['fits']['degenerate'])
        self.assertIn('degenerate', text)
        return doc, text

    def test_constant_t1_retains_boundary_and_withholds_likelihood(self):
        doc, text = self.check_case('T1_conforming', lambda r: 100)
        self.assertIsNone(doc['analysis']['reml']['fit']['restricted_loglik'])
        self.assertIn('singular', text)
        for value in doc['analysis']['estimates'].values():
            self.assertIsNone(value['lower'])
        self.assertTrue(all(not v['interval_available'] for v in doc['analysis']['variance_components'].values()))

    def test_constant_t2_does_not_claim_a_zero_contrast_is_significant(self):
        doc, _ = self.check_case('T2_conforming', lambda r: 100)
        for comp in doc['comparisons']:
            self.assertIsNone(comp['test']['p'])
            for value in comp['estimates']:
                self.assertEqual(value['estimate'], 0)
                self.assertIsNone(value['p'])
                self.assertIsNone(value['lower'])
        self.assertTrue(doc['analysis']['fits']['boundary'])

    def test_zero_error_with_nonzero_effect_does_not_manufacture_pvalue(self):
        doc, _ = self.check_case('T2_conforming', lambda r: 100 + int(r['A']))
        value = doc['comparisons'][0]['estimates'][0]
        self.assertNotEqual(value['estimate'], 0)
        self.assertIsNone(value['t'])
        self.assertIsNone(value['p'])
        self.assertIsNone(value['upper'])

    def test_constant_t3_withholds_all_affected_inference(self):
        doc, _ = self.check_case('T3_conforming', lambda r: 100)
        for value in doc['analysis']['estimates'].values():
            self.assertIsNone(value['lower'])
        self.assertTrue(all(c['test']['p'] is None for c in doc['comparisons']))

    def test_t3_zero_subplot_error_keeps_wholeplot_inference(self):
        doc, _ = self.check_case('T3_conforming', lambda r: int(r['unit'][1:]) ** 2)
        anova = doc['analysis']['anova']
        self.assertIsNotNone(anova['A']['p'])
        self.assertIsNone(anova['B']['p'])
        self.assertIsNone(anova['AB']['p'])
        for key, v in doc['analysis']['estimates'].items():
            if key.startswith('mean_A') or key.startswith('mean_B'):
                self.assertIsNotNone(v['lower'])

    def test_missing_site_zero_error_is_reported(self):
        decl = H.t2_declaration(exchangeable=True)
        rows = H.t2_rows()
        for row in rows:
            row['y'] = '100'
        rows.pop()
        with tempfile.TemporaryDirectory() as tmp:
            doc = build(*H.write(tmp, decl, rows))
            dumps(doc)
            render(doc)
        self.assertTrue(doc['analysis']['fits']['degenerate'])
        self.assertEqual(doc['allocation']['status'], 'withheld')
        self.assertIsNone(doc['comparisons'][0]['estimates'][0]['p'])


class InputAndCli(unittest.TestCase):
    def test_ambiguous_csv_headers_are_rejected(self):
        for text in ('y,y\n1,2\n', 'y, y \n1,2\n', 'y,\n1,2\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'headers'):
                read_table('SYNTHETIC', text=text)

    def test_csv_width_and_quotes_are_not_silently_repaired(self):
        for text in ('y\n1,2\n', 'x,y\n1\n', 'x,y\n"unfinished,2\n'):
            with self.subTest(text=text), self.assertRaises((ValueError, csv.Error)):
                read_table('SYNTHETIC', text=text)

    def test_explicit_missing_response_and_extra_named_column_are_retained(self):
        t = read_table('SYNTHETIC', text='x,y,unused\n1,,a\n2,NA,b\n')
        self.assertEqual([r['y'] for r in t.rows], ['', 'NA'])
        self.assertEqual(t.rows[0]['unused'], 'a')

    def test_bad_input_has_readable_cli_error_and_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            dp, cp = H.write(tmp, H.t2_declaration(), H.t2_rows())
            cp.write_text('y,y\n1,2\n')
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                result = main(['analyze', str(dp), str(cp), '--out', tmp + '/out'])
            self.assertEqual(result, 1)
            self.assertIn('CSV headers', err.getvalue())
            self.assertFalse((Path(tmp) / 'out').exists())

    def test_report_rejects_unrelated_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'input.json'; p.write_text('{}')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['report', str(p)]), 1)

    def test_cli_help_and_version(self):
        for args in (['--help'], ['--version'], ['analyze', '--help'], ['report', '--help'], ['explanations', '--help']):
            proc = subprocess.run([sys.executable, '-m', 'stratum', *args], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('maintainer', subprocess.check_output([sys.executable, '-m', 'stratum', '--help'], cwd=ROOT, text=True))

    def test_refusal_is_a_successful_cli_result(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            base = ROOT / 'fixtures/synthetic_wp2/CONF-03'
            self.assertEqual(main(['analyze', str(base / 'declaration_synthetic.yaml'),
                                   str(base / 'data_synthetic.csv'), '--out', tmp]), 0)
            self.assertEqual(json.loads((Path(tmp) / 'results.json').read_text())['decision']['evidence_decision'], 'REFUSE')

    def test_unavailable_diagnostics_are_not_assumption_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = build(*H.write(tmp, H.t2_declaration(r=2), H.t2_rows(r=2)))
        states = {a['assumption']: a['status'] for a in doc['assumptions']}
        self.assertNotEqual(states['equal variance across treatment levels'], 'pass')
        self.assertIn('unavailable', states['equal variance across treatment levels'])

    def test_component_caveat_survives_report_from_json_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = build(*H.write(tmp, H.t2_declaration(), H.t2_rows()))
        text = render(json.loads(dumps(doc)))
        self.assertIn('severe undercoverage', text)
        self.assertIn('VALIDATION.md', text)


if __name__ == '__main__':
    unittest.main()
