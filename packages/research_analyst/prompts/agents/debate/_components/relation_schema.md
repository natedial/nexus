## Relation schema

Each item in `relations[]` must be a JSON object with this shape:

```json
{
  "relation_type": "<supports|challenges|rebuts|concedes|duplicates|synthesizes>",
  "source_argument_id": "<local_id of an argument you created in this response>",
  "target_argument_id": "<argument_id being referenced>",
  "strength": 0.0,
  "explanation": "<brief why-this-link-exists summary or null>"
}
```

Rules:

- Use `challenges` for direct attacks, `rebuts` for defenses, and `concedes` only when the original claim should narrow or yield.
- `strength` is a calibrated `0.0-1.0` score for how forceful the relation is.
- The source must be an argument you create in this response. The target is an `argument_id` shown in `forum_context.arguments[]` (for example `proposal:1`). Relations that do not resolve are dropped.
