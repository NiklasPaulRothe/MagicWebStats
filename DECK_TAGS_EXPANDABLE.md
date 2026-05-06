# Deck Tags - Expandable Display

## Overview
Deck tags now display with a smart truncation system:
- **Maximum 3 tags** shown by default
- **"..." expander badge** appears when there are more than 3 tags
- **Hover to expand** - hovering over "..." reveals the remaining tags
- **Vertical expansion** - table row height increases, not width

## Visual Examples

### Example 1: 3 or Fewer Tags (No Expander)
```
Atraxa Superfriends
[combo] [control]
```

### Example 2: More Than 3 Tags (With Expander)

**Default State:**
```
Yuriko Ninjas
[aggro] [evasion] [extra turns] [...]
```

**Hover State (over "..."):**
```
Yuriko Ninjas
[aggro] [evasion] [extra turns] [...]
[unblockable] [card draw]
```

The row expands vertically to show the additional tags.

## Implementation Details

### JavaScript Logic

Both `user.html` and `deckstats.js` use the same logic:

```javascript
const tags = item['Tags'] || [];
if (tags.length > 0) {
    // Split tags into visible (first 3) and hidden (rest)
    const visibleTags = tags.slice(0, 3);
    const hiddenTags = tags.slice(3);
    
    // Render visible tags
    const visibleBadges = visibleTags.map(tag => 
        `<span class="deck-tag">${tag}</span>`
    ).join('');
    
    // If there are hidden tags, add expander and hidden container
    let expanderHtml = '';
    if (hiddenTags.length > 0) {
        const hiddenBadges = hiddenTags.map(tag => 
            `<span class="deck-tag">${tag}</span>`
        ).join('');
        expanderHtml = `<span class="deck-tag deck-tag-expander">...</span><div class="deck-tags-hidden">${hiddenBadges}</div>`;
    }
    
    tagsHtml = `<div class="deck-tags">${visibleBadges}${expanderHtml}</div>`;
}
```

### HTML Structure

**With 5 tags (combo, control, superfriends, midrange, value):**

```html
<td>
    <a href="/decks/show/DeckName">Deck Name</a>
    <div class="deck-tags">
        <span class="deck-tag">combo</span>
        <span class="deck-tag">control</span>
        <span class="deck-tag">superfriends</span>
        <span class="deck-tag deck-tag-expander">...</span>
        <div class="deck-tags-hidden">
            <span class="deck-tag">midrange</span>
            <span class="deck-tag">value</span>
        </div>
    </div>
</td>
```

### CSS Styling

#### Base Tag Styles
```css
.deck-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
    position: relative;
}

.deck-tag {
    display: inline-block;
    padding: 2px 6px;
    font-size: 0.7em;
    background-color: rgba(244, 196, 48, 0.15);
    border: 1px solid rgba(244, 196, 48, 0.3);
    border-radius: 3px;
    color: #b8a040;
    font-weight: normal;
    white-space: nowrap;
}
```

#### Expander Badge
```css
.deck-tag-expander {
    cursor: pointer;
    background-color: rgba(244, 196, 48, 0.2);  /* Slightly more opaque */
    border-color: rgba(244, 196, 48, 0.4);
    transition: background-color 0.2s ease;
}

.deck-tag-expander:hover {
    background-color: rgba(244, 196, 48, 0.3);  /* Even more visible on hover */
    border-color: rgba(244, 196, 48, 0.5);
}
```

#### Hidden Tags Container
```css
.deck-tags-hidden {
    display: none;              /* Hidden by default */
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
    width: 100%;                /* Full width of parent */
}

/* Show when hovering over expander */
.deck-tag-expander:hover + .deck-tags-hidden {
    display: flex;
}

/* Keep visible when hovering over the hidden tags themselves */
.deck-tags-hidden:hover {
    display: flex;
}
```

## Behavior Details

### Hover Interaction
1. **Hover over "..."**: Hidden tags appear below
2. **Move mouse to hidden tags**: They stay visible
3. **Move mouse away**: Hidden tags disappear

### Layout Behavior
- **Width**: Table column width remains constant
- **Height**: Table row expands vertically to accommodate hidden tags
- **Wrapping**: Hidden tags wrap within the column width
- **Alignment**: Hidden tags align with visible tags

### Visual Feedback
- **Expander badge**: Slightly more opaque than regular tags
- **Hover state**: Expander becomes even more visible on hover
- **Cursor**: Changes to pointer over the expander
- **Transition**: Smooth 0.2s fade on hover

## Edge Cases

### 0 Tags
- No tags displayed
- No expander
- Row looks normal

### 1-3 Tags
- All tags displayed
- No expander
- Normal layout

### 4+ Tags
- First 3 tags displayed
- Expander badge shown
- Remaining tags hidden until hover

### Very Long Tag Names
- Tags use `white-space: nowrap` to prevent breaking
- Tags may extend the column width if necessary
- Hidden tags wrap to multiple lines if needed

## Files Modified

1. **app/templates/user.html** - User deck stats JavaScript
2. **app/static/js/deckstats.js** - Global deck stats JavaScript
3. **app/static/css/gamead.css** - User deck stats styling
4. **app/static/css/deckstats.css** - Global deck stats styling

## Testing Scenarios

1. **Deck with 0 tags**: Should look normal, no tags shown
2. **Deck with 1 tag**: Single tag shown, no expander
3. **Deck with 3 tags**: All 3 tags shown, no expander
4. **Deck with 4 tags**: 3 tags + expander, 1 hidden
5. **Deck with 10 tags**: 3 tags + expander, 7 hidden
6. **Hover over expander**: Hidden tags appear below
7. **Hover over hidden tags**: They stay visible
8. **Move mouse away**: Hidden tags disappear

## Advantages

✅ **Clean default view** - Maximum 3 tags keeps the table compact  
✅ **No information loss** - All tags accessible via hover  
✅ **Vertical expansion** - Table width stays consistent  
✅ **Visual consistency** - Expander uses same styling as tags  
✅ **Intuitive interaction** - Hover is a natural discovery mechanism  
✅ **Smooth UX** - Transition effects make it feel polished  
✅ **Accessible** - Works with mouse hover (keyboard support could be added)  
