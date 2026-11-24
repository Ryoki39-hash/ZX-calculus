# Stage 2 — Predeclared hypothesis decisions

Run: `stage2-20261124T070501Z`; code: `b309dd8f7ec1a8799b0a9a79b1ffee089d71cc97`.

Predeclared descriptive thresholds, not significance tests. Missing/failed verification or undefined required metrics makes the corresponding hypothesis inconclusive; no replacement seeds or omitted failures.

| Hypothesis | Decision | Frozen criterion |
| --- | --- | --- |
| H1 | supported | At 4q/L80, >=8/10 verified T-nonincreasing strict-2Q wins and median g2>0; AND at 8q/L80, >=8/10 strict-2Q increases and median g2<0. |
| H2 | supported | Both Toffoli ladders (5q,7q) have strict T reduction AND strict 2Q increase. |
| H3 | supported | Both QFT inputs (5q,7q) have strict 2Q increase AND strict depth increase. |
| H4 | supported | At 8q, g2(L160)-g2(L80)>0 in >=8/10 matched seeds AND median paired difference>0. |
| H5 | supported | S2(reuse)-S2(unique)>0 in >=8/10 matched seeds AND median paired difference>0; T nonincrease is reported separately. |
| H6 | not_supported | (ZX2Q-Gate2Q)_cascade > (ZX2Q-Gate2Q)_disjoint for the two fixed 6q inputs. |

Exact counts, observed denominators, missing values, minima, medians, maxima and every paired observation are retained in [hypotheses.json](hypotheses.json).
