# Version History Feature

## Overview
The version history feature allows users to view a complete timeline of all version changes made to a deck.

## User Interface

### Accessing Version History
On the deck show page (`/decks/show/<deckname>`), next to the version number, there is a small link icon (🔗) with a tooltip that says "Version History". Clicking this icon takes you to the version history page.

### Version History Page
The version history page displays a table with the following columns:
- **Date**: When the version change was made (timestamp)
- **Change Type**: The type of change (color-coded):
  - **Rework** (red) - Major version increment
  - **Patch** (cyan) - Patch version increment
  - **Change** (light green) - Minor change increment
- **Previous Version**: The version number before the change
- **New Version**: The version number after the change (highlighted in gold)

The table uses the same styling as other tables in the application for consistency.

## Implementation Details

### Files Modified
1. **app/templates/decks/show.html**
   - Added link icon next to version display
   - Icon has hover tooltip "Version History"

2. **app/decks/routes.py**
   - Added `version_history()` route at `/decks/version-history/<deckname>`
   - Fetches all version history entries for the deck
   - Orders by timestamp descending (newest first)

3. **app/templates/decks/version_history.html** (new file)
   - Displays version history in a table
   - Color-codes change types
   - Shows "Back to Deck" link
   - Displays empty state message if no history exists

### Route Details
```python
@bp.route('/version-history/<deckname>', methods=['GET'], strict_slashes=False)
@login_required
def version_history(deckname):
```

- Requires login
- Fetches deck by name (404 if not found)
- Queries `DeckVersionHistory` table for all entries related to the deck
- Orders results by timestamp descending

### Styling
- Uses existing `deckpage.css` for consistent styling
- Table uses `.deck-games-table` class (same as game history table)
- Color scheme:
  - Rework: `#ff6b6b` (red)
  - Patch: `#4ecdc4` (cyan)
  - Change: `#95e1d3` (light green)
  - New version: `#f4c430` (gold)

## Empty State
If a deck has no version history yet, the page displays a friendly message:
> "No version history available yet. Version changes will appear here once you update the deck."

## Navigation
- Link icon on deck show page → Version history page
- "Back to Deck" link on version history page → Deck show page
