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
    "first_pct": 28.57,
    "avg_removal_played": 1.4,
    "avg_removal_targeted": 0.8
  }
]
```

`avg_removal_played` / `avg_removal_targeted` are per-game averages over games
where removal was tracked; they are `null` when a player has fewer than 5
tracked games (shown as "–" on the Players page).

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
    ],
    "color_key": "2:34"
  }
]
```

`color_key` is a sort key for the Colors table: `"<number of colors>:<WUBRG
rank digits>"` (W=0 … G=4), so sorting by it gives colorless first, then
mono-colors in W→U→B→R→G order, then two-color pairs, and so on.

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
    "id": 12,
    "name": "Meren Reanimator",
    "commander": "Meren of Clan Nel Toth",
    "color_identity": "Golgari",
    "games": 15,
    "last_played": "15.1.2025",
    "last_played_iso": "2025-01-15",
    "wins": 6,
    "winrate_pct": 40.0,
    "avg_win_turns": 9.5,
    "win_turns_count": 6,
    "decklist": "https://archidekt.com/decks/123",
    "image_uri": "https://cards.scryfall.io/large/front/…jpg",
    "color_imgs": ["https://example.com/B.svg", "https://example.com/G.svg"],
    "tags": ["reanimator"]
  }
]
```

Used by the **My Deck Stats** card grid. `last_played` is the legacy German
date format (`D.M.YYYY`); `last_played_iso` is `YYYY-MM-DD` (display + sorting).
`avg_win_turns` / `win_turns_count` count only **this player's** wins with the
deck that have a recorded turn count (`avg_win_turns` is `null` without any).

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
    "color_imgs": ["https://example.com/G.svg"],
    "tags": [],
    "image_uri": null,
    "avg_win_turns": null,
    "win_turns_count": 0,
    "last_played_iso": "2024-06-02"
  }
]
```

Same card fields as the active-deck endpoint, so the **Archived** view of My
Deck Stats renders identical cards (plus a Reactivate button for the owner or a
maintainer, which posts to `POST /decks/dearchive/<id>`).

---

## `POST /api/quick-add-player`

Add a new player. Maintainer or admin.

**Auth:** login required + maintainer role or higher  
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

Add a new deck. Maintainer or admin.

**Auth:** login required + maintainer role or higher  
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

---

## `GET /api/deck-participant-averages/<deckname>?since=`

Private per-deck averages (mana/gas, mulligans, land drops, …) shown in the
collapsed "Private stats" section of the deck page.

**Auth:** login required + maintainer role or higher

---

# Page-level JSON endpoints (outside `/api`)

These back interactive page features. All require login; POSTs need the
`X-CSRFToken` header (read from `<meta name="csrf-token">`) and return
`{"ok": false, "message": "…"}` with a 4xx status on error.

## Deck folders (My Decks)

### `POST /decks/<deck_id>/folder`

Move a deck into a folder, or to the top level with `null`.
Body: `{"folder_id": 3 | null}` → `{"ok": true}`.
Errors: `403` not your deck · `404` deck or target folder not found/not yours.

### `POST /decks/folders/<folder_id>/parent`

Move a folder (with its decks and subfolders) under another folder, or to the
top level with `null`. Used by the ⋮ "Move to" menu.
Body: `{"parent_id": 5 | null}` → `{"ok": true}`.
Errors: `400` non-integer target, the folder itself, or one of its own
subfolders (cycle guard) · `403` not your folder · `404` folder/target not
found or not yours. Audit-logged as `folder_move`.

## Collection

### `POST /collection/import` (multipart form)

Fields: `csv_file` (Archidekt collection export or ManaBox single-folder
export, ≤10 MB, UTF-8), `mode` = `replace` (default — the file becomes the
whole collection) or `add` (counts are added to matching entries). The format
is detected from the CSV header; ManaBox values are mapped onto the stored
tokens (`normal/foil/etched` → `Normal/Foil/Etched`, `near_mint` → `NM`, `en`
→ `EN`, …). Redirects back with flash messages; rows whose exact Scryfall
printing isn't in the database are skipped and listed.

### `GET /collection/printings?name=<exact card name>`

Step 2 of "Add card": all locally stored printings of a card, newest first.
`200` → `{"ok": true, "name": "…", "printings": [{"id", "name", "set_code",
"set_name", "released_at", "image"}]}` (`image` is the front face in Scryfall's
`normal` size, or `null`). `400` without a name, `404` unknown name.

### `POST /collection/add`

Step 3 of "Add card". Body: `{"card_id": "<scryfall id>", "count": 1-999,
"finish": "Normal"|"Foil"|"Etched", "language": "EN"|"DE"|…}`. Condition is
`NM`. Merges into an existing entry with the same printing + finish +
condition + language (count is added), otherwise creates one.
`200` → `{"ok": true, "created": bool, "count": <new total>}`.
Errors: `400` invalid count/finish/language · `404` unknown card.

### `POST /collection/entry/<entry_id>/remove`

Remove from the card popup. Body: `{"amount": "one" | "all"}` — `one` lowers
the count by 1 (deleting the entry at 0), `all` deletes the whole stack.
`200` → `{"ok": true, "remaining": <count, 0 when deleted>}`.
Errors: `400` unknown amount · `403` another player's entry · `404` unknown entry.

## Role management (HTML forms, admin only)

- `GET /auth/manage/roles` — list users with their role and linked player.
- `POST /auth/manage/roles/<user_id>` — form field `role` (`user` |
  `maintainer` | `admin`); refuses to demote the last remaining admin.
- `POST /auth/manage/roles/<user_id>/player` — reassign the user's linked
  player; refuses a player already linked to another user.
