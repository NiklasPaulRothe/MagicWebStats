# API Reference

All endpoints are prefixed with `/api` and require `@login_required` unless noted otherwise.

Base URL: `/api`

---

## `GET /api/data`

All-time player statistics (excludes cEDH games from counts). Only returns players active within the last 365 days.

**Auth:** login required

**Response:** `200 OK`

```json
[
  {
    "name": "Alice",
    "games": 42,
    "wins": 15,
    "winrate_pct": 35.71,
    "early_sol_ring": 8,
    "sol_ring_pct": 19.05,
    "first": 12,
    "first_pct": 28.57
  }
]
```

---

## `GET /api/data/<year>`

Player statistics filtered to a specific calendar year. Same shape as `/api/data`.

**Auth:** login required

**Parameters:**
- `year` (path, int) — calendar year (e.g., 2024)

**Response:** `200 OK` — same format as `/api/data`

---

## `GET /api/data/years`

Distinct years that have game data, ordered descending.

**Auth:** login required

**Response:** `200 OK`

```json
[2025, 2024, 2023]
```

---

## `GET /api/color-data`

Color identity statistics (game count, wins, winrate). Excludes cEDH games.

**Auth:** login required

**Response:** `200 OK`

```json
[
  {
    "name": "Golgari",
    "games": 28,
    "wins": 9,
    "winrate_pct": 32.14,
    "color_imgs": [
      "https://example.com/B.svg",
      "https://example.com/G.svg"
    ]
  }
]
```

---

## `GET /api/deck-data`

Statistics for all active decks.

**Auth:** login required

**Response:** `200 OK`

```json
[
  {
    "deck_name": "Meren Reanimator",
    "player_name": "Alice",
    "commander": "Meren of Clan Nel Toth",
    "color_identity": "Golgari",
    "games": 15,
    "wins": 6,
    "winrate_pct": 40.0,
    "avg_win_turns": 9.5,
    "win_turns_count": 6,
    "decklist": "https://archidekt.com/decks/123",
    "elo": 1523.4,
    "color_imgs": ["https://example.com/B.svg", "https://example.com/G.svg"],
    "tags": ["reanimator", "midrange"]
  }
]
```

---

## `GET /api/userdecks/<player_id>`

Active decks for a specific player.

**Auth:** login required

**Parameters:**
- `player_id` (path, int) — player's database ID

**Response:** `200 OK`

```json
[
  {
    "name": "Meren Reanimator",
    "commander": "Meren of Clan Nel Toth",
    "color_identity": "Golgari",
    "games": 15,
    "last_played": "2025-01-15",
    "wins": 6,
    "winrate_pct": 40.0,
    "decklist": "https://archidekt.com/decks/123",
    "color_imgs": ["https://example.com/B.svg", "https://example.com/G.svg"],
    "tags": ["reanimator"]
  }
]
```

---

## `GET /api/userdecks/archive/<player_id>`

Archived (inactive) decks for a specific player.

**Auth:** login required

**Parameters:**
- `player_id` (path, int) — player's database ID

**Response:** `200 OK`

```json
[
  {
    "id": 7,
    "name": "Old Omnath",
    "commander": "Omnath, Locus of Mana",
    "color_identity": "Mono-Green",
    "games": 8,
    "wins": 2,
    "winrate_pct": 25.0,
    "decklist": null,
    "color_imgs": ["https://example.com/G.svg"]
  }
]
```

---

## `POST /api/quick-add-player`

Add a new player. Admin only.

**Auth:** login required + admin role  
**CSRF:** X-CSRFToken header required

**Request body:**

```json
{
  "name": "Bob"
}
```

**Response:** `201 Created`

```json
{
  "name": "Bob"
}
```

**Errors:**
- `400` — name missing
- `409` — player already exists

---

## `POST /api/quick-add-deck`

Add a new deck. Admin only.

**Auth:** login required + admin role  
**CSRF:** X-CSRFToken header required

**Request body:**

```json
{
  "name": "Korvold Treasures",
  "commander": "Korvold, Fae-Cursed King",
  "player": "Alice",
  "color_identity": "Jund",
  "partner": null,
  "cedh": false
}
```

**Response:** `201 Created`

```json
{
  "name": "Korvold Treasures",
  "commander": "Korvold, Fae-Cursed King",
  "player": "Alice"
}
```

**Errors:**
- `400` — missing required field, commander not in DB, player not found, color identity invalid
- `409` — deck name already exists

---

## `GET /api/cards/autocomplete?q=`

Card name autocomplete. Returns up to 10 matches.

**Auth:** login required

**Parameters:**
- `q` (query, str) — search term (minimum 2 characters)

**Response:** `200 OK`

```json
["Korvold, Fae-Cursed King", "Korvold, Gleeful Glutton"]
```

Returns `[]` if `q` is less than 2 characters.
