## Relation schema

Each item in `relations[]` must be a JSON object with this shape:

```json
{
  "relation_type": "<supports|challenges|rebuts|concedes|duplicates|synthesizes>",
  "source_argument_id": "<argument_id providing the relation>",
  "target_argument_id": "<argument_id being referenced>",
  "strength": 0.0,
  "explanation": "<brief why-this-link-exists summary or null>"
}
```

Rules:

- Use `challenges` for direct attacks, `rebuts` for defenses, and `concedes` only when the original claim should narrow or yield.
- `strength` is a calibrated `0.0-1.0` score for how forceful the relation is.
- Every relation must connect concrete `argument_id`s from `forum_context.arguments[]` or arguments you create in the same response.
