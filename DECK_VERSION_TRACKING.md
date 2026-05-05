# Deck Version Tracking Implementation

## Overview
This implementation adds a version history tracking system for decks. Every time a deck version is changed through the edit menu (Change, Patch, or Rework), an entry is saved to the database with an optional comment describing the changes.

## Database Changes

### New Table: `deck_version_history`
Located in schema: `data_owner`

**Columns:**
- `id` (SERIAL PRIMARY KEY) - Auto-incrementing unique identifier
- `deck_id` (INTEGER NOT NULL) - Foreign key to Decks.id
- `change_type` (VARCHAR(20) NOT NULL) - Type of change: 'change', 'patch', or 'rework'
- `previous_version` (INTEGER NOT NULL) - Version number before the change
- `previous_patch` (INTEGER NOT NULL) - Patch number before the change
- `previous_change` (INTEGER NOT NULL) - Change number before the change
- `new_version` (INTEGER NOT NULL) - Version number after the change
- `new_patch` (INTEGER NOT NULL) - Patch number after the change
- `new_change` (INTEGER NOT NULL) - Change number after the change
- `comment` (TEXT) - Optional comment describing what changed
- `timestamp` (TIMESTAMP NOT NULL) - When the change was made (defaults to current timestamp)

**Indexes:**
- `idx_deck_version_history_deck_id` - For fast lookups by deck
- `idx_deck_version_history_timestamp` - For chronological queries

### Installation
Run the SQL script to create the table:
```bash
psql -U your_username -d your_database -f scripts/create_deck_version_history.sql
```

If you already created the table without the comment column, run:
```bash
psql -U your_username -d your_database -f scripts/add_comment_to_version_history.sql
```

## Code Changes

### 1. Model Addition (`app/models.py`)
Added new `DeckVersionHistory` model class with comment field to represent the version history table.

### 2. Form Updates (`app/decks/forms.py`)
Added `version_comment` TextAreaField to the DeckEditForm for users to enter optional comments when updating versions.

### 3. Route Updates (`app/decks/routes.py`)
Updated the `deck_edit` route to:
- Capture the comment from the form
- Save version history entries with comments when any of the three version buttons are clicked

Each button now:
1. Retrieves the comment from the form (if provided)
2. Creates a `DeckVersionHistory` entry with the previous and new version numbers and the comment
3. Updates the deck's version numbers
4. Updates the appropriate date field (Last_Change, last_patch, or Last_Rework)
5. Commits both changes to the database

### 4. Template Updates

**Edit Template (`app/templates/decks/edit.html`):**
- Added a comment textarea field below the version update section
- Consolidated the three version buttons into a single form
- Comment field is shared by all three buttons (Reworked, Patched, Changed)
- Styled to match the existing form design

**Version History Template (`app/templates/decks/version_history.html`):**
- Added "Comment" column to the version history table
- Displays comments with proper text wrapping
- Shows "No comment" in italics if no comment was provided

## Usage

### Updating Deck Version with Comment

When editing a deck at `/decks/edit/<deckname>`:
1. Scroll to the "Version Update" section
2. (Optional) Enter a comment in the "Version Change Comment" field describing what changed
3. Click one of three buttons:
   - **Deck Reworked** - For major changes (e.g., 1.2.3 → 2.0.0)
   - **Deck Patched** - For moderate updates (e.g., 1.2.3 → 1.3.0)
   - **Deck Changed** - For minor changes (e.g., 1.2.3 → 1.2.4)

The comment will be saved with the version change and displayed in the version history.

### Viewing Version History

1. Navigate to a deck page
2. Click the 🔗 icon next to the version number
3. View the complete version history with comments

## Features

- **Optional Comments**: Comments are optional - you can update versions without adding a comment
- **Shared Comment Field**: One comment field is used for all three version buttons
- **Comment Display**: Comments are displayed in the version history table with proper formatting
- **Empty State**: If no comment is provided, "No comment" is shown in italics

## Future Enhancements

Potential additions:
- Edit comments after they've been saved
- Add tags or categories to version changes
- Filter version history by change type
- Compare changes between versions
- Export version history as changelog with comments
