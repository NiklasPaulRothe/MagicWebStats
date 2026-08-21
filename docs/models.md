# Models

All tables live under the configurable `DB_SCHEMA` (default: `magic_stats_owner`). Models use SQLAlchemy 2.0 mapped columns.

## Core Tables

### `players`

Player identity. Each player has a unique name.

| Column | Type | Notes |
|--------|------|-------|
| id | int | PK |
| name | str | unique, not null |
| created_at | datetime | server default |
| updated_at | datetime | auto-update |

### `decks`

Deck definitions — each deck belongs to one player.

| Column | Type | Notes |
|--------|------|-------|
| id | int | PK |
| name | str | unique deck name |
| active | bool | whether deck is in use |
| commander | str | commander card name |
| player_id | int | FK → players |
| color_identity | str | FK → color_identities |
| partner | str? | partner commander (optional) |
| elo_rating | float? | default 1500, CHECK >= 0 |
| version / patch / change | int | semantic versioning, CHECK >= 0 |
| last_rework / last_patch / last_change | date | version timestamps |
| cedh | bool? | competitive EDH flag |
| decklist | str? | external decklist URL |
| image_uri | str? | commander card image |
| created_at / updated_at | datetime | timestamps |

### `games`

Individual game records.

| Column | Type | Notes |
|--------|------|-------|
| id | int | PK |
| date | date | not null |
| winner_id | int? | FK → players |
| first_player_id | int? | FK → players |
| turns | int? | CHECK >= 0 |
| planechase | bool | default false |
| final_blow | str? | how the winner won |
| first_ko_turn | int? | turn of first elimination |
| first_ko_by | str? | who eliminated first |
| cedh | bool? | competitive game flag |
| added_by_user_id | int? | FK → users |
| created_at / updated_at | datetime | timestamps |

### `participants`

Many-to-many linking players + decks to games. Composite PK: (game_id, player_id).

| Column | Type | Notes |
|--------|------|-------|
| game_id | int | PK, FK → games |
| player_id | int | PK, FK → players |
| deck_id | int | FK → decks |
| seat | int? | seating position, CHECK >= 1 |
| early_sol_ring | bool | T1/T2 Sol Ring |
| mulligans | int? | CHECK >= 0 |
| landdrops | int? | consecutive land drops (-1 = all) |
| lands | int? | total lands in deck |
| enough_mana | bool? | subjective assessment |
| enough_gas | bool? | had enough card draw/threats |
| deckplan | bool? | executed game plan |
| unanswered_threats | bool? | faced unanswered threats |
| loss_without_answer | bool? | lost without having answers |
| selfmade_win | bool? | won through own strategy |
| fun_moments | bool? | memorable moments |
| removal_played / targeted_by_removal | int? | removal stats |
| protection_played | int? | protection spells used |
| comments | str? | freeform notes |

## Color System

### `color_identities`

All valid MTG color identity combinations (e.g., "Azorius", "Sultai", "Colorless").

| Column | Type | Notes |
|--------|------|-------|
| name | str | PK (e.g., "Golgari") |
| amount | int | number of colors (0–5) |

### `colors`

The five colors plus Colorless.

| Column | Type | Notes |
|--------|------|-------|
| name | str | PK (e.g., "White") |
| abbreviation | str | single letter (W, U, B, R, G) |
| img | str? | URL to color symbol image |

### `color_components`

Maps color identities to their component colors. Composite PK: (color_identity, color).

## Card Database

### `cards`

Card data (sourced from Scryfall via `scripts/fetch_card_data.py`).

| Column | Type | Notes |
|--------|------|-------|
| id | str | PK (Scryfall UUID) |
| oracle_id | str | groups printings |
| name | str | indexed |
| mana_cost | str? | |
| cmc | float | converted mana cost |
| type_line | str | |
| oracle_text | text? | rules text |
| layout | str | normal, transform, etc. |
| set_code / set_name | str | set information |
| rarity | str | |
| released_at | date? | |

### Related Tables

- **`card_faces`** — multi-face card data (face_index, image_uri, per-face text)
- **`card_colors`** — card's colors (composite PK: card_id + color)
- **`card_color_identity`** — card's color identity components
- **`card_keywords`** — card keywords (Flying, Trample, etc.)
- **`card_legalities`** — format legality (card_id + format → status)
- **`oracle_tags`** — community tags by oracle_id

## Deck Composition

### `deck_component`

Cards in a deck (deck_id, card_id, count, name).

### `deck_tags`

Freeform tags on decks (unique per deck_id + tag). Used for filtering in the UI.

## Tracking

### `achievements`

Deck-specific achievements (title, description, target amount, achieved count).

### `deck_version_history`

Tracks version bumps (change_type, previous/new version numbers, comment, timestamp).

## Auth & Audit

### `users`

Application users with role-based access (username, email, password_hash, role, player_id link).

### `audit_log`

Append-only log of state-changing actions (timestamp, user_id, username, action, entity_type, entity_id, details).

## Views

### `v_color_usage`

Aggregated color usage across all active decks: likelihood, average, deck_percentage per color.

### `v_color_usage_player`

Per-player color breakdown: white/blue/black/red/green percentages, deck count, average number of colors.

Both views are defined in `scripts/schema.sql` and mapped as read-only models in `app/viewmodels.py`.
