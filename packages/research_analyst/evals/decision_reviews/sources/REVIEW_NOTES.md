# Jev shadow review notes

Run: Jev 1.13.0, question-set v2, 5-document shadow sample.
Review notes only; original run outputs remain unchanged.

## doc_002 / chunk-6:assertion-2

Review date: 2026-09-30
Status: agreed by Nate

### Sentence reviewed

> The 2s10s spread should compress to 30bp as front-end remains anchored by Fed patience while long-end faces term premium pressure from supply dynamics.

### Original Jev classification

- recommendation: 0.65
- assertion: 0.35

### Agreed review outcome

- statement_type: assertion
- is_forecast: yes
- is_causal: yes
- contains_reasoning_bridge: yes
- is_trade_or_action: no

Scope: the sentence itself, excluding the prepended section title.

Rationale: The sentence makes a market call (2s10s compresses to
30bp) and offers causal reasoning (Fed patience anchors the front
end; supply dynamics pressure long-end term premium). It does
not prescribe a trade or position. Reasoning being present does
not establish that it is economically consistent.

### Input issue to investigate

The stored input prepends:

> We recommend positioned for a flatter curve through mid-year. The 2s10s spread s:

This prefix may influence the recommendation classification.
That is a hypothesis, not a confirmed cause.

## doc_003 / chunk-7:assertion-1

Review date: 2026-10-02
Status: agreed by Nate

### Sentence reviewed

> We see no compelling reason to reposition for major USD moves in either direction.

### Original Jev classification

- statement_type: assertion (0.93)
- is_substantive_author_claim: 0.86
- is_observation: 0.81
- is_forecast: 0.58
- is_trade_or_action: not among the leading outputs shown in the review table

### Agreed review outcome

- statement_type: recommendation
- is_forecast: no
- is_causal: no
- contains_reasoning_bridge: no
- is_trade_or_action: yes

Scope: this sentence alone, excluding the following tactical-trades sentence.

Rationale: The author recommends maintaining the current positioning rather
than initiating a major directional USD position. A recommendation to refrain
from action is still an action decision. The sentence neither predicts the
dollar's path nor provides a causal mechanism or reasoning bridge.

### Question-set issue to investigate

Question-set v2 may under-recognize negative or status-quo recommendations,
such as advice not to reposition. This is a hypothesis, not a confirmed cause.

