# Gold annotation feature backlog

Running notes from human–agent co-reading sessions. Add an item when the current gold-record schema or workflow cannot faithfully represent an annotation judgment.

## Link semantics

### Mutually exclusive claims

The link schema needs a way to state that two claims describe outcomes that cannot both hold under the same conditions. `contrasts_with` preserves disagreement but loses the stronger logical constraint.

Candidate link type: `mutually_exclusive`.

### Falsification relationships

The link schema needs a way to state that an observed outcome or claim would falsify another claim. This is distinct from contrast: it records an empirical test relationship and may be directional.

Candidate link type: `falsifies`.

Open design questions:

- Whether `falsifies` links a claim to another claim, a future observation, or both.
- Whether mutually exclusive forecast paths require their conditions to be normalized before validation.
- Whether final records should require an explicit evaluation horizon for falsifiable forecasts.

### Projection sensitivity

The link schema needs to represent a causal factor that can strengthen or weaken a forecast path over time without treating that factor as direct support, qualification, or a competing claim. This matters when the same causal claim can affect several projections differently as conditions evolve.

Candidate directional link types: `strengthens` and `weakens`.

Open design questions:

- Whether the link should carry an effective horizon or scenario condition.
- Whether strength should be qualitative or permit a quantified sensitivity.
- Whether one causal claim may strengthen one projection while weakening another.
