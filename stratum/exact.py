"""Exact rational linear algebra for indicator designs (DECISIONS.md D-049).

Every design matrix in the evidence checks is a 0/1 indicator matrix, so it is held
sparsely: one row per unit, as the list of column indices that are 1 in that row.
All arithmetic is in `fractions.Fraction`, so rank and estimability are decided
exactly. There is no floating-point rank decision and no tolerance.

Facts used (standard linear-model results, e.g. Searle, *Linear Models*):
  - rank(X) = rank(XᵀX), and the row space of X equals the column space of XᵀX;
  - c is estimable (cᵀb is the same for every solution of the normal equations) iff
    c lies in the row space of X, i.e. iff XᵀX·x = c has a solution;
  - for estimable c, cᵀ(XᵀX)⁻c is the same for every generalized inverse, and
    equals cᵀx for any solution x of XᵀX·x = c. With residual variance σ², the
    variance of the estimate of cᵀβ is σ²·cᵀ(XᵀX)⁻c;
  - the hat-matrix diagonal h_ii = x_iᵀ(XᵀX)⁻x_i, and the fitted values Xb (b any
    solution of XᵀX·b = Xᵀy) do not depend on the choice of solution.
"""
from functools import lru_cache
from fractions import Fraction
from typing import List, Optional, Sequence

Q = Fraction


def rref(matrix: Sequence[Sequence[Fraction]]):
    """Reduced row echelon form, computed exactly. Returns (rows, pivot columns)."""
    m = [[Q(v) for v in row] for row in matrix]
    pivots = []
    r = 0
    ncols = len(m[0]) if m else 0
    for c in range(ncols):
        pivot = next((i for i in range(r, len(m)) if m[i][c] != 0), None)
        if pivot is None:
            continue
        m[r], m[pivot] = m[pivot], m[r]
        lead = m[r][c]
        m[r] = [v / lead for v in m[r]]
        for i in range(len(m)):
            if i != r and m[i][c] != 0:
                f = m[i][c]
                m[i] = [a - f * b for a, b in zip(m[i], m[r])]
        pivots.append(c)
        r += 1
        if r == len(m):
            break
    return m, pivots


def rank(matrix: Sequence[Sequence[Fraction]]) -> int:
    return len(rref(matrix)[1]) if matrix else 0


def solve(a: Sequence[Sequence[Fraction]], b: Sequence[Fraction]) -> Optional[List[Fraction]]:
    """One exact solution of a·x = b, or None when the system is inconsistent."""
    n = len(a[0]) if a else 0
    aug = [list(row) + [Q(v)] for row, v in zip(a, b)]
    m, pivots = rref(aug)
    if n in pivots:                       # a pivot in the right-hand column: 0 = nonzero
        return None
    x = [Q(0)] * n                        # free variables set to 0
    for row, c in zip(m, pivots):
        x[c] = row[n]
    return x


def gram(rows: Sequence[Sequence[Fraction]]) -> List[List[Fraction]]:
    """XᵀX of a dense matrix given by its rows (used for a numeric trend column)."""
    ncols = len(rows[0])
    return [[sum((Q(r[a]) * Q(r[b]) for r in rows), Q(0)) for b in range(ncols)]
            for a in range(ncols)]


def quad(xtx: Sequence[Sequence[Fraction]], c: Sequence[Fraction]) -> Optional[Fraction]:
    """cᵀ(XᵀX)⁻c for an estimable c; None when c is not estimable."""
    x = solve(xtx, c)
    if x is None:
        return None
    return sum((Q(ci) * xi for ci, xi in zip(c, x)), Q(0))


@lru_cache(maxsize=256)
def _geometry(rows, ncols):
    """Exact normal-matrix geometry, keyed only by the design, never by responses."""
    xtx = [[Q(0)] * ncols for _ in range(ncols)]
    for row in rows:
        for a in row:
            for b in row:
                xtx[a][b] += 1
    _, pivots = rref(xtx)
    # Independent columns give a nonsingular principal Gram submatrix.
    k = len(pivots)
    aug = [[xtx[i][j] for j in pivots] + [Q(l == m) for m in range(k)]
           for l, i in enumerate(pivots)]
    reduced, _ = rref(aug)
    inverse = tuple(tuple((j, v) for j, v in zip(pivots, row[k:]) if v)
                    for row in reduced)
    return tuple(tuple(r) for r in xtx), tuple(pivots), inverse


class Design:
    """A 0/1 design: rows[i] lists the columns equal to 1 in row i."""

    def __init__(self, rows: Sequence[Sequence[int]], ncols: int):
        self.rows = [tuple(r) for r in rows]
        self.ncols = ncols
        matrix, self._pivots, self._inverse = _geometry(tuple(self.rows), ncols)
        self.xtx = [list(r) for r in matrix]

    def _solution(self, rhs):
        x = [Q(0)] * self.ncols
        for i, row in zip(self._pivots, self._inverse):
            x[i] = sum((v * rhs[j] for j, v in row), Q(0))
        return x

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def rank(self) -> int:
        return len(self._pivots)

    def quad(self, c: Sequence[Fraction]) -> Optional[Fraction]:
        """cᵀ(XᵀX)⁻c for an estimable c; None when c is not estimable."""
        x = self._solution(c)
        if any(sum((row[j]*x[j] for j in self._pivots), Q(0)) != ci
               for row, ci in zip(self.xtx, c)):
            return None
        return sum((Q(ci) * xi for ci, xi in zip(c, x)), Q(0))

    def estimable(self, c: Sequence[Fraction]) -> bool:
        return self.quad(c) is not None

    def row_vector(self, i: int) -> List[Fraction]:
        v = [Q(0)] * self.ncols
        for a in self.rows[i]:
            v[a] += 1
        return v

    def leverages(self) -> List[Fraction]:
        return list(_leverages(tuple(self.rows), self.ncols))

    def fitted(self, y: Sequence[Fraction]) -> List[Fraction]:
        xty = [Q(0)] * self.ncols
        for r, v in zip(self.rows, y):
            for a in r:
                xty[a] += v
        b = self._solution(xty)          # always consistent: Xᵀy is in the column space
        return [sum((b[a] for a in r), Q(0)) for r in self.rows]


@lru_cache(maxsize=256)
def _leverages(rows, ncols):
    design = Design(rows, ncols)
    unique = {r: design.quad(design.row_vector(i)) for i, r in enumerate(rows)}
    return tuple(unique[r] for r in rows)


def proportional(table: Sequence[Sequence[int]]) -> bool:
    """True iff n_ij·n = n_i·n_j in every cell (no association; exact integers)."""
    n = sum(sum(row) for row in table)
    rows = [sum(row) for row in table]
    cols = [sum(col) for col in zip(*table)] if table else []
    return all(table[i][j] * n == rows[i] * cols[j]
               for i in range(len(table)) for j in range(len(cols)))


def chi_square(table: Sequence[Sequence[int]]) -> Fraction:
    """Pearson χ² of a contingency table with no empty margin, exactly."""
    n = sum(sum(row) for row in table)
    rows = [sum(row) for row in table]
    cols = [sum(col) for col in zip(*table)]
    total = Q(0)
    for i, row in enumerate(table):
        for j, o in enumerate(row):
            e = Q(rows[i] * cols[j], n)
            total += (o - e) ** 2 / e
    return total


def cramers_v_squared(table: Sequence[Sequence[int]]) -> Optional[Fraction]:
    """V² = χ² / (n·(min(R, C) − 1)); None when either factor has a single level.
    Empty rows or columns are dropped first (only observed levels count)."""
    t = [row for row in table if sum(row)]
    keep = [j for j in range(len(t[0]))] if t else []
    keep = [j for j in keep if any(row[j] for row in t)]
    t = [[row[j] for j in keep] for row in t]
    k = min(len(t), len(keep))
    if k < 2:
        return None
    n = sum(sum(row) for row in t)
    return chi_square(t) / (n * (k - 1))


def det(matrix: Sequence[Sequence[Fraction]]) -> Fraction:
    """The exact determinant of a square matrix, by Gaussian elimination."""
    m = [[Q(v) for v in row] for row in matrix]
    n = len(m)
    if any(len(row) != n for row in m):
        raise ValueError("determinant needs a square matrix")
    out = Q(1)
    for c in range(n):
        pivot = next((i for i in range(c, n) if m[i][c] != 0), None)
        if pivot is None:
            return Q(0)
        if pivot != c:
            m[c], m[pivot] = m[pivot], m[c]
            out = -out
        out *= m[c][c]
        inv = 1 / m[c][c]
        m[c] = [v * inv for v in m[c]]
        for i in range(c + 1, n):
            if m[i][c] != 0:
                f = m[i][c]
                m[i] = [a - f * b for a, b in zip(m[i], m[c])]
    return out
