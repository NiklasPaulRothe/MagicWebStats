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

    function refreshDeckCount() {
        var sub = main.querySelector('.my-decks-sub');
        var remaining = main.querySelectorAll('.deck-grid .deck-card').length;
        if (sub) {
            var folderPart = sub.textContent.indexOf('·') !== -1
                ? sub.textContent.slice(sub.textContent.indexOf('·'))
                : '';
            sub.textContent = remaining + (remaining === 1 ? ' deck ' : ' decks ') + folderPart;
        }
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
})();
