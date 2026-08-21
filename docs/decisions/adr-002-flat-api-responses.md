# ADR-002: Flat JSON API Responses with snake_case Keys

## Status

Accepted

## Context

The legacy API wrapped all values in single-element arrays and used PascalCase keys:

```json
{
  "Name": ["Alice"],
  "Games": [42],
  "Wins": [15],
  "WinratePct": [35.71]
}
```

This made frontend code unnecessarily complex — every value access required `data.Name[0]` instead of `data.name`. The pattern originated from an early prototype and was never revisited.

## Decision

Normalize all API responses to flat objects with snake_case keys. Missing/unavailable values use `null` instead of empty arrays or omitted keys.

**New format:**
```json
{
  "name": "Alice",
  "games": 42,
  "wins": 15,
  "winrate_pct": 35.71
}
```

## Consequences

### Positive

- Standard REST conventions — predictable for any consumer
- Simpler frontend code — direct property access
- Consistent with Python/Flask ecosystem conventions
- Easier to type (TypeScript interfaces map directly)
- `null` for missing values is explicit and standard

### Negative

- Required a coordinated frontend + backend update
- Any external consumers (if any) needed to update simultaneously
- Brief period of instability during rollout

### Implementation

- Backend: `app/api/formatters.py` handles the transformation from query results to flat snake_case dicts
- Frontend: JavaScript updated to use direct property access
- Both changes deployed together as a single coordinated release
