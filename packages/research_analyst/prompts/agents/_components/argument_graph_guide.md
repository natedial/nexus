## Using `argument_graph`

The `argument_graph` tool queries **already-resolved argument maps** across publishers. A position / side is always a **publisher** (GS, MS, Citi, Barclays, …), never a thesis / contrarian / positioning lens. Use it when you need who agrees or disagrees on a claim and on what evidence. It does **not** retrieve corpus passages — that is `research_search`.

Parameters:
- `query` (string, optional) — one of `interpretation_gaps`, `independence`, `contradictions`, `backed_vs_asserted`, or `all` (default).
  - `interpretation_gaps` — same `referent_key`, opposing conclusions, distinct publishers
  - `independence` — same claim, disjoint evidence (**robust**) vs shared evidence (**herding**)
  - `contradictions` — a claim standing against a referent cited for the other side
  - `backed_vs_asserted` — one house evidenced a claim another only asserted
- `claim_key` (string, optional) — restrict to a resolved key such as `claim:fed_policy:hike:down`
- `limit` (int, optional) — default 8; max 8 hits per query type

When to call:
1. After you can name the claim or datapoint at issue.
2. Prefer this over `research_search` when the question is "which houses split on this, and why?"
3. Attribute every hit to the named publisher. Never treat a specialist lens as a side.

Empty hits mean the stored maps do not yet resolve a cross-author join. That is a real signal, not a tool failure — do not invent a dissenting house to fill the gap.
