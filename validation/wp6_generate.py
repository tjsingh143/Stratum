"""SYNTHETIC WP6 parametric inputs. No analysis or expectation registry access.

The design and numerical parameters come from the frozen manifest (D-089–D-092).
Return ordinary declaration/data inputs for the unmodified public analysis entry point.
"""
import math


def shape(c):
    t = c['template']
    if t == 'T1':
        return 1, c['groups'], c['wafers_per_group'], c['sites_per_wafer']
    if t == 'T2':
        return c['treatment_levels'], c['units_per_level'], c['wafers_per_run'], c['sites_per_wafer']
    return c['wholeplot_levels_a'], c['wholeplots_per_level_r'], 1, c['subplot_levels_b']


def declaration(c):
    t = c['template']
    a, r, w, s = shape(c)
    top = 'wafer' if t == 'T3' else 'run'
    h = [{'name': top, 'id_column': 'unit', 'count': a*r}]
    if t != 'T3':
        h.append({'name': 'wafer', 'id_column': 'middle', 'nested_in': top,
                  'count_per_parent': w, 'exchangeable': True})
    h.append({'name': 'position' if t == 'T3' else 'site', 'id_column': 'observation',
              'nested_in': 'wafer', 'count_per_parent': s, 'exchangeable': t != 'T3'})
    d = {'stratum_declaration': 1, 'claimed_template': t,
         'response': {'column': 'y', 'units': None if t == 'T3' else 'angstrom'},
         'hierarchy': h, 'treatments': [], 'nuisance_factors': [], 'comparisons': []}
    if t != 'T1':
        d['treatments'] = [{'name': 'A', 'column': 'A', 'levels': [str(i+1) for i in range(a)],
                            'applied_to': top, 'replicates_per_level': r,
                            'assignment': {'method': 'systematic' if c.get('variant') == 'systematic'
                                           else 'randomized'}}]
        d['comparisons'] = [{'id': 'A', 'kind': 'pairwise', 'factors': ['A'], 'levels': ['1','2']}]
    if t == 'T3':
        d['treatments'].append({'name': 'B', 'column': 'observation',
                                'levels': [str(i+1) for i in range(s)], 'applied_to': 'position',
                                'replicates_per_level': a*r, 'assignment': {'method': 'inherent'}})
        d['comparisons'] += [{'id': 'B', 'kind': 'pairwise', 'factors': ['B'], 'levels': ['1','2']},
                             {'id': 'AB', 'kind': 'interaction', 'factors': ['A','B']}]
        d['split_plot'] = {'whole_plot_factor': 'A', 'subplot_factor': 'B'}
    if c.get('block_levels'):
        d['nuisance_factors'].append({'name': 'block', 'column': 'block', 'role': 'block',
                                     'recorded_at': top, 'crossed_with': 'A',
                                     'levels': [str(i+1) for i in range(c['block_levels'])]})
    if c['condition'] in ('complete_confounding', 'partial_confounding'):
        n = a if c['condition'] == 'complete_confounding' else 2
        d['nuisance_factors'].append({'name': 'chamber', 'column': 'block', 'role': 'recorded',
                                     'recorded_at': top, 'levels': [str(i+1) for i in range(n)]})
    if c['condition'] == 'aliased_grouping_steps':
        d['nuisance_factors'].append({'name': 'batch', 'column': 'batch', 'role': 'recorded',
                                     'recorded_at': 'wafer' if t == 'T1' else top})
    return d


def generate(c, rng, params, effects):
    """Generate all responses before missingness; no replicate is redrawn."""
    t, condition = c['template'], c['condition']
    a, r, w, s = shape(c)
    v = c.get('variance_components', c.get('stratum_variances'))
    top_sd = math.sqrt(v['sigma2_wholeplot'] if t == 'T3' else v['sigma2_run'])
    low_sd = math.sqrt(v['sigma2_subplot'] if t == 'T3' else v['sigma2_site'])
    mid_sd = 0 if t == 'T3' else math.sqrt(v['sigma2_wafer'])
    order = list(range(a*r))
    if condition == 'drift_in_run_order' and c['variant'] == 'randomized':
        rng.shuffle(order)
    rank = {unit: i for i, unit in enumerate(order)}
    rows = []
    def draw(level):
        z = rng.gauss(0, 1)
        if condition == 'heavy_tails' and c['variant'] == level:
            df = params['heavy_tails']['df']
            z /= math.sqrt(2*rng.gammavariate(df/2, 1)/(df-2))
        return z
    for i in range(a):
        for j in range(r):
            u = i*r+j
            block, fixed = 0, 0.0
            if t == 'T2':
                fixed = c['tau'][i]
            if c.get('block_levels'):
                k = c['block_levels']
                block = j % k
                fixed += (block/(k-1) - .5)*params['blocking']['centered_block_range_in_top_sd']*top_sd
                if condition == 'block_interaction':
                    d = effects['T2_treatment_difference']['value']  # D-090, including null cells
                    fixed += d/4 * (1 if i == 0 else -1) * (1 if block == 0 else -1)
            if condition == 'complete_confounding':
                block = i
                fixed += (i-(a-1)/2)*params[condition]['nuisance_offset_in_top_sd']*top_sd
            if condition == 'partial_confounding':
                counts = params[condition][t+'_table'][i]
                block = 0 if j < counts[0] else 1
                fixed += (block-.5)*top_sd
            if condition == 'drift_in_run_order':
                fixed += (rank[u]/(a*r-1)-.5)*params[condition]['range_in_top_sd']*top_sd
            scale = (math.sqrt(params[condition]['variance_multiplier'])
                     if condition == 'unequal_variances_4to1'
                     and i in params[condition]['high_levels'][t] else 1)
            top_effect = draw('top')*top_sd*scale
            for jmid in range(w):
                mid_effect = 0 if t == 'T3' else draw('middle')*mid_sd
                for k in range(s):
                    fixed_sub = 0
                    if t == 'T3':
                        e = c['effects']
                        fixed_sub = (e.get('A', {}).get('alpha', [0]*a)[i]
                                     + e.get('B', {}).get('beta', [0]*s)[k]
                                     + e.get('AB', {}).get('gamma', [[0]*s for _ in range(a)])[i][k])
                    y = v['mu'] + fixed + fixed_sub + top_effect + mid_effect + draw('lowest')*low_sd
                    if condition == 'outliers' and rng.random() < params[condition]['probability']:
                        y += params[condition]['positive_shift_in_lowest_sd']*low_sd
                    rows.append({'unit': f'U{u+1:03}', 'middle': str(jmid+1), 'observation': str(k+1),
                                 'A': str(i+1), 'block': str(block+1),
                                 'batch': f'Batch{u+1}-{jmid+1}' if t == 'T1' else f'Batch{u+1}',
                                 'y': format(y, '.12f')})
    if condition == 'missing_sites':
        if t == 'T2':
            for row in rows:
                if rng.random() < params[condition]['probability']:
                    row['y'] = ''
        else:
            rows[rng.randrange(len(rows))]['y'] = ''
    return rows


def missing_pattern(rows):
    """Input-only MCAR classification, independent of the Stratum checker."""
    units, middles, surviving_u, surviving_m = set(), set(), set(), set()
    lost = 0
    for row in rows:
        u, m = row['unit'], (row['unit'], row['middle'])
        units.add(u); middles.add(m)
        if row['y']:
            surviving_u.add(u); surviving_m.add(m)
        else:
            lost += 1
    return ('empty_run' if surviving_u != units else 'empty_wafer' if surviving_m != middles
            else 'site_loss' if lost else 'no_loss')
