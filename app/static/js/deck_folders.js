/* Deck folders: drag decks onto folder cards to move them, and create folders.
 *
 * Scoped to the "My Decks" page. Uses native HTML5 drag-and-drop and the
 * project's X-CSRFToken fetch convention (see card_modal.js). The whole deck
 * card is an <a>; we suppress the click that would otherwise fire after a drag
 * so dragging never navigates to the deck page.
 */
(function () {
    'use strict';

    var main = document.querySelector('.my-decks');
    if (!main) {
        return;
    }

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function postJSON(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken()
            },
            body: JSON.stringify(body || {})
        }).then(function (resp) {
            return resp.json().then(function (data) {
                if (!resp.ok || !data || !data.ok) {
                    throw new Error((data && data.message) || ('HTTP ' + resp.status));
                }
                return data;
            });
        });
    }

    /* ---------------------------------------------------------------- Drag */

    var draggingDeckId = null;
    var suppressClick = false;

    function onDragStart(e) {
        var card = e.target.closest ? e.target.closest('.deck-card[draggable="true"]') : null;
        if (!card) {
            return;
        }
        draggingDeckId = card.getAttribute('data-deck-id');
        card.classList.add('deck-card-dragging');
        if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = 'move';
            // Some browsers require data to be set for the drag to proceed.
            try { e.dataTransfer.setData('text/plain', draggingDeckId); } catch (err) { /* noop */ }
        }
    }

    function onDragEnd(e) {
        var card = e.target.closest ? e.target.closest('.deck-card') : null;
        if (card) {
            card.classList.remove('deck-card-dragging');
        }
        // A click event fires right after a successful drag on some browsers;
        // swallow the next one so we don't navigate to the deck page.
        suppressClick = true;
        setTimeout(function () { suppressClick = false; }, 50);
        draggingDeckId = null;
    }

    function folderTargets() {
        return main.querySelectorAll('.folder-card[data-folder-id]');
    }

    function targetFolderId(card) {
        // Empty string (root / up-to-root) means null folder.
        var raw = card.getAttribute('data-folder-id');
        return raw === '' ? null : parseInt(raw, 10);
    }

    function onDragOver(e) {
        if (draggingDeckId === null) {
            return;
        }
        var card = e.target.closest ? e.target.closest('.folder-card[data-folder-id]') : null;
        if (!card || card.classList.contains('folder-new')) {
            return;
        }
        e.preventDefault(); // allow drop
        if (e.dataTransfer) {
            e.dataTransfer.dropEffect = 'move';
        }
        card.classList.add('folder-card-dragover');
    }

    function onDragLeave(e) {
        var card = e.target.closest ? e.target.closest('.folder-card[data-folder-id]') : null;
        if (card) {
            card.classList.remove('folder-card-dragover');
        }
    }

    function onDrop(e) {
        var card = e.target.closest ? e.target.closest('.folder-card[data-folder-id]') : null;
        if (!card || draggingDeckId === null) {
            return;
        }
        e.preventDefault();
        card.classList.remove('folder-card-dragover');

        var deckId = draggingDeckId;
        var folderId = targetFolderId(card);
        var deckCard = main.querySelector('.deck-card[data-deck-id="' + deckId + '"]');

        postJSON('/decks/' + encodeURIComponent(deckId) + '/folder', { folder_id: folderId })
            .then(function () {
                // The deck left the current folder view: remove its card and
                // bump the target folder's deck count.
                if (deckCard) {
                    deckCard.parentNode.removeChild(deckCard);
                }
                bumpFolderCount(card, 1);
                refreshDeckCount();
            })
            .catch(function (err) {
                flashError(deckCard, err.message);
            });
    }

    function bumpFolderCount(folderCard, delta) {
        var countEl = folderCard.querySelector('.folder-card-count');
        if (!countEl) {
            return;
        }
        var m = countEl.textContent.match(/(\d+)/);
        var n = (m ? parseInt(m[1], 10) : 0) + delta;
        countEl.textContent = n + (n === 1 ? ' deck' : ' decks');
    }

    // Rebuild the "N decks · M folders" line from what's on the page now.
    function refreshDeckCount() {
        var sub = main.querySelector('.my-decks-sub');
        if (!sub) {
            return;
        }
        var decks = main.querySelectorAll('.deck-grid .deck-card').length;
        var folders = main.querySelectorAll('.folder-grid .folder-item').length;
        sub.textContent = decks + (decks === 1 ? ' deck' : ' decks')
            + (folders ? ' \u00b7 ' + folders + (folders === 1 ? ' folder' : ' folders') : '');
    }

    function flashError(deckCard, message) {
        if (deckCard) {
            deckCard.classList.add('deck-card-error');
            setTimeout(function () { deckCard.classList.remove('deck-card-error'); }, 1200);
        }
        console.error('Move failed:', message);
    }

    // Bind drag handlers at the document level (delegation) so cards added
    // later still work.
    main.addEventListener('dragstart', onDragStart);
    main.addEventListener('dragend', onDragEnd);
    main.addEventListener('dragover', onDragOver);
    main.addEventListener('dragleave', onDragLeave);
    main.addEventListener('drop', onDrop);

    // Suppress the post-drag click so dragging a card never navigates.
    main.addEventListener('click', function (e) {
        if (suppressClick) {
            var link = e.target.closest ? e.target.closest('.deck-card-link') : null;
            if (link) {
                e.preventDefault();
                e.stopPropagation();
            }
        }
    }, true);

    /* ------------------------------------------------------ Create folder */

    var backdrop = document.getElementById('folder-dialog-backdrop');
    var nameInput = document.getElementById('folder-name-input');
    var errorEl = document.getElementById('folder-dialog-error');
    var newBtn = document.getElementById('new-folder-btn');
    var cancelBtn = document.getElementById('folder-cancel-btn');
    var createBtn = document.getElementById('folder-create-btn');

    function openDialog() {
        if (!backdrop) { return; }
        if (errorEl) { errorEl.hidden = true; errorEl.textContent = ''; }
        if (nameInput) { nameInput.value = ''; }
        backdrop.hidden = false;
        if (nameInput) { nameInput.focus(); }
    }

    function closeDialog() {
        if (backdrop) { backdrop.hidden = true; }
    }

    function currentFolderId() {
        var raw = main.getAttribute('data-current-folder-id');
        return raw ? parseInt(raw, 10) : null;
    }

    function submitFolder() {
        var name = (nameInput && nameInput.value || '').trim();
        if (!name) {
            showDialogError('Please enter a folder name.');
            return;
        }
        var url = main.getAttribute('data-create-folder-url') || '/decks/folders';
        postJSON(url, { name: name, parent_id: currentFolderId() })
            .then(function () {
                // Reload so the new folder card renders with server-side markup
                // and ordering, keeping client and server in sync.
                window.location.reload();
            })
            .catch(function (err) {
                showDialogError(err.message || 'Could not create folder.');
            });
    }

    function showDialogError(msg) {
        if (errorEl) {
            errorEl.textContent = msg;
            errorEl.hidden = false;
        }
    }

    if (newBtn) { newBtn.addEventListener('click', openDialog); }
    if (cancelBtn) { cancelBtn.addEventListener('click', closeDialog); }
    if (createBtn) { createBtn.addEventListener('click', submitFolder); }
    if (backdrop) {
        backdrop.addEventListener('click', function (e) {
            if (e.target === backdrop) { closeDialog(); }
        });
    }
    if (nameInput) {
        nameInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); submitFolder(); }
            if (e.key === 'Escape') { closeDialog(); }
        });
    }

    /* ------------------------------------------------- ⋮ action menu
     * Touch-friendly alternative to drag-and-drop. One shared popover is
     * positioned next to the clicked ⋮ button. "Move to" lists the folders on
     * this page: the parent ("Up one level", when inside a folder) and the
     * folder tiles shown — minus the item itself for a folder. */

    var menu = document.getElementById('item-menu');
    var actionsPanel = menu ? menu.querySelector('[data-panel="actions"]') : null;
    var movePanel = menu ? menu.querySelector('[data-panel="move"]') : null;
    var targetsBox = menu ? menu.querySelector('[data-role="targets"]') : null;
    var menuBtn = null;      // the ⋮ button that opened the menu
    var menuItem = null;     // the deck/folder <li> it belongs to

    function menuItems() {
        var panel = movePanel && !movePanel.hidden ? movePanel : actionsPanel;
        return panel ? Array.prototype.slice.call(panel.querySelectorAll('.item-menu-item')) : [];
    }

    function showPanel(name) {
        actionsPanel.hidden = name !== 'actions';
        movePanel.hidden = name !== 'move';
        var items = menuItems();
        if (items.length) { items[0].focus(); }
        positionMenu();
    }

    function buildTargets() {
        targetsBox.innerHTML = '';
        var selfFolderId = menuItem.classList.contains('folder-item')
            ? menuItem.getAttribute('data-folder-id') : null;
        var tiles = main.querySelectorAll('.folder-grid .folder-up, .folder-grid .folder-item');
        var count = 0;
        Array.prototype.forEach.call(tiles, function (tile) {
            var id = tile.getAttribute('data-folder-id');
            if (selfFolderId !== null && id === selfFolderId) { return; }
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'item-menu-item';
            btn.setAttribute('role', 'menuitem');
            btn.setAttribute('data-target-id', id);
            var icon = document.createElement('span');
            icon.className = 'item-menu-icon';
            icon.setAttribute('aria-hidden', 'true');
            icon.textContent = tile.classList.contains('folder-up') ? '\u21A9' : '\uD83D\uDCC1';
            var label = document.createElement('span');
            label.className = 'item-menu-label';
            label.textContent = tile.getAttribute('data-folder-name') || 'Folder';
            btn.appendChild(icon);
            btn.appendChild(label);
            targetsBox.appendChild(btn);
            count++;
        });
        if (!count) {
            var none = document.createElement('p');
            none.className = 'item-menu-empty';
            none.textContent = 'No other folders on this page.';
            targetsBox.appendChild(none);
        }
    }

    function positionMenu() {
        if (!menuBtn || menu.hidden) { return; }
        var r = menuBtn.getBoundingClientRect();
        var w = menu.offsetWidth, h = menu.offsetHeight;
        var vw = document.documentElement.clientWidth, vh = window.innerHeight;
        // Right-align under the button; flip above when there's no room below.
        var left = Math.min(Math.max(8, r.right - w), vw - w - 8);
        var top = r.bottom + 4;
        if (top + h > vh - 8 && r.top - h - 4 > 8) { top = r.top - h - 4; }
        menu.style.left = left + 'px';
        menu.style.top = Math.max(8, top) + 'px';
    }

    function openMenu(btn) {
        if (menuBtn === btn) { closeMenu(); return; }   // toggle
        closeMenu();
        menuBtn = btn;
        menuItem = btn.closest('.deck-card, .folder-item');
        btn.setAttribute('aria-expanded', 'true');
        menu.hidden = false;
        showPanel('actions');
    }

    function closeMenu(restoreFocus) {
        if (!menu || menu.hidden) { menuBtn = null; menuItem = null; return; }
        menu.hidden = true;
        if (menuBtn) {
            menuBtn.setAttribute('aria-expanded', 'false');
            if (restoreFocus) { menuBtn.focus(); }
        }
        menuBtn = null;
        menuItem = null;
    }

    function moveTo(targetRaw) {
        var item = menuItem;
        var targetId = targetRaw === '' ? null : parseInt(targetRaw, 10);
        var targetTile = main.querySelector('.folder-grid .folder-card[data-folder-id="' + targetRaw + '"]');
        closeMenu();
        if (!item) { return; }

        var isDeck = item.classList.contains('deck-card');
        var request = isDeck
            ? postJSON('/decks/' + encodeURIComponent(item.getAttribute('data-deck-id')) + '/folder',
                       { folder_id: targetId })
            : postJSON('/decks/folders/' + encodeURIComponent(item.getAttribute('data-folder-id')) + '/parent',
                       { parent_id: targetId });

        request.then(function () {
            // The item left this page: drop its card and update the counts.
            item.parentNode.removeChild(item);
            if (isDeck && targetTile) { bumpFolderCount(targetTile, 1); }
            refreshDeckCount();
        }).catch(function (err) {
            if (isDeck) {
                flashError(item, err.message);
            } else {
                item.classList.add('folder-card-error');
                setTimeout(function () { item.classList.remove('folder-card-error'); }, 1200);
                console.error('Move failed:', err.message);
            }
        });
    }

    if (menu && actionsPanel && movePanel && targetsBox) {
        // Open/close from any ⋮ button (delegated: works for every card).
        main.addEventListener('click', function (e) {
            var btn = e.target.closest ? e.target.closest('.item-menu-btn') : null;
            if (!btn) { return; }
            e.preventDefault();
            e.stopPropagation();
            openMenu(btn);
        });

        menu.addEventListener('click', function (e) {
            var item = e.target.closest ? e.target.closest('.item-menu-item') : null;
            if (!item) { return; }
            var action = item.getAttribute('data-action');
            if (action === 'move') { buildTargets(); showPanel('move'); }
            else if (action === 'back') { showPanel('actions'); }
            else if (item.hasAttribute('data-target-id')) { moveTo(item.getAttribute('data-target-id')); }
        });

        // Click outside closes.
        document.addEventListener('click', function (e) {
            if (menu.hidden) { return; }
            if (menu.contains(e.target) || (menuBtn && menuBtn.contains(e.target))) { return; }
            closeMenu();
        });

        // Keyboard: Escape closes, arrows move between items.
        document.addEventListener('keydown', function (e) {
            if (menu.hidden) { return; }
            if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); return; }
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                var items = menuItems();
                if (!items.length) { return; }
                var i = items.indexOf(document.activeElement);
                i = e.key === 'ArrowDown' ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
                items[i].focus();
                e.preventDefault();
            }
        });

        // Keep it attached to its button; close if the page scrolls it away.
        window.addEventListener('resize', function () { closeMenu(); });
        document.addEventListener('scroll', function (e) {
            if (!menu.hidden && !menu.contains(e.target)) { positionMenu(); }
        }, { capture: true, passive: true });
    }
})();
