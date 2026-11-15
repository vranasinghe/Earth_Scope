"""Multiple-testing correction for per-grid-cell trend tests.

A region contains tens to hundreds of grid cells. Testing each one at α = 0.05
means roughly 5 % of trendless cells would still look "significant". These
functions adjust a whole family of p-values at once.

* ``fdr_bh`` — Benjamini & Hochberg (1995) step-up procedure. Controls the
  expected proportion of false discoveries (FDR) at level α when the tests are
  independent or positively dependent (PRDS; Benjamini & Yekutieli 2001).
  Neighbouring grid cells are usually positively correlated, which is the
  favourable case, but arbitrary spatial dependence is not covered by a proof.
* ``fdr_by`` — Benjamini & Yekutieli (2001). Multiplies the BH adjustment by
  c(m) = Σ_{k=1..m} 1/k, which controls the FDR under ANY dependence, at the
  cost of fewer discoveries.

Adjusted p-values ("q-values" in the UI) are the smallest FDR level at which a
hypothesis would be rejected: ``q_(i) = min_{k ≥ i} min(1, c·m·p_(k)/k)``
over the p-values sorted ascending (c = 1 for BH). A cell is a discovery when
``q ≤ α`` — the BH step-up rule ``p_(k) ≤ k·α/m``.

Implemented directly (a few lines, no runtime dependency); the test-suite
checks it against ``statsmodels.stats.multitest.multipletests`` and the worked
example in Benjamini & Hochberg (1995).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

CORRECTIONS = {
    "none": "No multiple-testing correction (raw p-values)",
    "fdr_bh": "Benjamini–Hochberg false discovery rate",
    "fdr_by": "Benjamini–Yekutieli false discovery rate (valid under any dependence)",
}


def is_valid_p(p: float | None) -> bool:
    return p is not None and isinstance(p, (int, float)) and math.isfinite(p) and 0.0 <= p <= 1.0


def adjust_pvalues(pvalues: Sequence[float | None], method: str) -> list[float | None]:
    """Adjust a family of p-values. Invalid entries (None, NaN, outside [0, 1])
    are left out of the family and returned as ``None``.

    ``method`` is one of ``none``, ``fdr_bh``, ``fdr_by``.
    """
    if method not in CORRECTIONS:
        raise ValueError(f"Unsupported correction method: {method!r}")
    idx = [i for i, p in enumerate(pvalues) if is_valid_p(p)]
    out: list[float | None] = [None] * len(pvalues)
    if not idx:
        return out
    p = np.array([float(pvalues[i]) for i in idx])
    if method == "none":
        for k, i in enumerate(idx):
            out[i] = float(p[k])
        return out
    m = len(p)
    c = float(np.sum(1.0 / np.arange(1, m + 1))) if method == "fdr_by" else 1.0
    order = np.argsort(p, kind="mergesort")      # stable: ties keep their input order
    ranked = p[order] * c * m / np.arange(1, m + 1)
    q_sorted = np.minimum(1.0, np.minimum.accumulate(ranked[::-1])[::-1])
    q = np.empty(m)
    q[order] = q_sorted
    for k, i in enumerate(idx):
        out[i] = float(q[k])
    return out


def family_size(pvalues: Sequence[float | None]) -> int:
    return sum(1 for p in pvalues if is_valid_p(p))
