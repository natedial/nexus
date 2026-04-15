## Confidence calibration

All `confidence` fields take a float in `[0.0, 1.0]`. Use this rubric:

- `0.90–1.00` — The document provides direct quantitative evidence (a cited number, a dated forecast, a policy statement). A competent analyst would not push back.
- `0.75–0.89` — Strong qualitative support with explicit argumentation in the document, but not numerically pinned.
- `0.60–0.74` — Inferred from adjacent claims or the author's framing; a reasonable analyst could reach a different read.
- `0.40–0.59` — Speculative extension; the document gestures at it but does not argue for it.
- `< 0.40` — Do not emit. Either strengthen or drop the claim.

Prefer dropping weak claims over diluting confident ones. A short list of well-supported claims beats a long list of hedged ones.
