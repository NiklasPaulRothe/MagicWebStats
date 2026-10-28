/* Owner-only editor for a deck card's collection marker (deck overview).
 *
 * Clicking a card's corner marker opens a small popover to set the physical
 * status (unset / in deck / proxy) and the finish + language the "in deck"
 * claim is matched against. Saving posts to the component collection endpoint
 * and updates the marker in place. Printing editing reuses the card modal's
 * existing "change printing" flow, so it isn't duplicated here.
 */
(function () {
    'use strict';

    var main = document.querySelector('.deck-overview');
    if (!main || !main.getAttribute('data-is-owner')) {
        return; // not the owner; markers are static badges
    }
    var deckId = main.getAttribute('data-deck-id');
    var editor = document.getElementById('cc-editor');
    if (!editor) {
        return;
    }

    var finishSel = document.getElementById('cc-finish');
    var languageInput = document.getElementById('cc-language');
    var noteEl = document.getElementById('cc-editor-note');
    var statusBtns = editor.querySelectorAll('.cc-status-btn');
    var saveBtn = document.getElementById('cc-editor-save');
    var cancelBtn = document.getElementById('cc-editor-cancel');

    var activeMarker = null;      // the .cc-marker being edited
    var chosenStatus = 'unset';

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function setChosenStatus(value) {
        chosenStatus = value;
        statusBtns.forEach(function (b) {
            b.classList.toggle('is-active', b.getAttribute('data-value') === value);
        });
        // Finish/language only matter for an "in deck" claim; keep them enabled
        // for proxy/unset too (so the owner can pre-set them), just hint it.
    }

    // Select a value in a <select>, adding it as an option first if it isn't
    // already one (so a card's current finish/language is always pre-selected
    // even if it's not among the collection-derived options).
    function selectWithFallback(sel, value) {
        if (!value) {
            if (sel.options.length) { sel.selectedIndex = 0; }
            return;
        }
        var found = Array.prototype.some.call(sel.options, function (o) {
            return o.value === value;
        });
        if (!found) {
            var opt = document.createElement('option');
            opt.value = value;
            opt.textContent = value;
            sel.appendChild(opt);
        }
        sel.value = value;
    }

    function openEditor(marker) {
        activeMarker = marker;
        setChosenStatus(marker.getAttribute('data-physical-status') || 'unset');
        // Pre-populate finish and language with the card's current values.
        selectWithFallback(finishSel, marker.getAttribute('data-finish') || '');
        selectWithFallback(languageInput, marker.getAttribute('data-language') || '');
        noteEl.hidden = true;
        noteEl.textContent = '';

        // Position the popover near the marker, kept within the viewport.
        var r = marker.getBoundingClientRect();
        editor.hidden = false;
        var top = window.scrollY + r.bottom + 6;
        var left = window.scrollX + r.left;
        var maxLeft = window.scrollX + document.documentElement.clientWidth - editor.offsetWidth - 8;
        if (left > maxLeft) { left = maxLeft; }
        if (left < 8) { left = 8; }
        editor.style.top = top + 'px';
        editor.style.left = left + 'px';
    }

    function closeEditor() {
        editor.hidden = true;
        activeMarker = null;
    }

    // After a status or printing change the card may move between groups in the
    // "By collection" board and its markers change colour in every board.
    // Rather than surgically mutate three server-grouped boards in JS (which is
    // error-prone — stale groups, duplicate stacks, wrong counts), reload the
    var STATUS_CLASSES = [
        'cc-in_deck_ok', 'cc-in_deck_faulty', 'cc-proxy', 'cc-available',
        'cc-owned_no_copy', 'cc-owned_other', 'cc-not_owned'
    ];
    var STATUS_TITLES = {
        in_deck_ok: 'In deck — a real copy is allocated',
        in_deck_faulty: 'In deck — not enough matching copies in your collection',
        proxy: 'Proxy',
        available: 'Available — you own a free matching copy',
        owned_no_copy: 'Owned, but every matching copy is used in a deck',
        owned_other: 'Owned in a different printing',
        not_owned: 'Not owned'
    };

    // Update a single marker's status class / title / data-* in place.
    function setMarkerStatus(marker, status, physicalStatus, finish, language) {
        STATUS_CLASSES.forEach(function (c) { marker.classList.remove(c); });
        if (status) {
            marker.classList.add('cc-' + status);
            marker.setAttribute('data-status', status);
            if (STATUS_TITLES[status]) {
                marker.setAttribute('title', STATUS_TITLES[status]);
                marker.setAttribute('aria-label', 'Collection: ' + STATUS_TITLES[status]);
            }
        }
        if (physicalStatus !== undefined) {
            marker.setAttribute('data-physical-status', physicalStatus || 'unset');
        }
        if (finish !== undefined) { marker.setAttribute('data-finish', finish || ''); }
        if (language !== undefined) { marker.setAttribute('data-language', language || ''); }
    }

    // Fetch the server-rendered "By collection" board and swap it in wholesale.
    // The server is the single source of truth for grouping/order/counts, so
    // the swapped-in board is identical to a fresh page load — no per-node
    // moves, no duplicates, no drift.
    function refreshCollectionBoard() {
        var wrap = document.getElementById('collection-board-wrap');
        if (!wrap) { return Promise.resolve(); }
        return fetch('/decks/' + encodeURIComponent(deckId) + '/collection-board', {
            headers: { 'Accept': 'text/html' }
        }).then(function (resp) {
            if (!resp.ok) { throw new Error('HTTP ' + resp.status); }
            return resp.text();
        }).then(function (html) {
            wrap.innerHTML = html;
        });
    }
    // Exposed so the card modal's printing change can refresh the board too.
    window.ccRefreshCollectionBoard = refreshCollectionBoard;
    // Exposed so the card modal can update a component's markers in place after
    // a printing change (status comes from the printing endpoint's response).
    window.updateComponentMarkers = function (componentId, data) {
        document.querySelectorAll(
            '.cc-marker[data-component-id="' + componentId + '"]'
        ).forEach(function (m) {
            setMarkerStatus(m, data.status, data.physical_status, data.finish, data.language);
        });
    };

    function save() {
        if (!activeMarker) { return; }
        var componentId = activeMarker.getAttribute('data-component-id');
        var body = {
            physical_status: chosenStatus,
            finish: finishSel.value,
            language: languageInput.value.trim()
        };
        saveBtn.disabled = true;
        fetch('/decks/' + encodeURIComponent(deckId) + '/component/' +
              encodeURIComponent(componentId) + '/collection', {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken()
            },
            body: JSON.stringify(body)
        }).then(function (resp) {
            return resp.json().then(function (data) {
                if (!resp.ok || !data.ok) {
                    throw new Error((data && data.message) || ('HTTP ' + resp.status));
                }
                return data;
            });
        }).then(function (data) {
            // Update this card's markers in the type/category boards in place
            // (those boards don't regroup by status, so only the dot changes).
            document.querySelectorAll(
                '.cc-marker[data-component-id="' + componentId + '"]'
            ).forEach(function (m) {
                setMarkerStatus(m, data.status, data.physical_status, data.finish, data.language);
            });
            closeEditor();
            // The collection board regroups — pull the fresh server-rendered
            // version and swap it in.
            return refreshCollectionBoard();
        }).catch(function (err) {
            noteEl.textContent = String(err.message || err);
            noteEl.hidden = false;
        }).finally(function () {
            saveBtn.disabled = false;
        });
    }

    // Open on marker click (markers are rendered in every grouping board).
    document.addEventListener('click', function (e) {
        var marker = e.target.closest ? e.target.closest('.cc-marker.cc-editable') : null;
        if (marker) {
            e.preventDefault();
            e.stopPropagation();
            if (activeMarker === marker && !editor.hidden) {
                closeEditor();
            } else {
                openEditor(marker);
            }
            return;
        }
        // Click outside the editor closes it.
        if (!editor.hidden && !editor.contains(e.target)) {
            closeEditor();
        }
    });

    // Keyboard open (Enter/Space) on a focused marker.
    document.addEventListener('keydown', function (e) {
        var marker = e.target.closest ? e.target.closest('.cc-marker.cc-editable') : null;
        if (marker && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            openEditor(marker);
        }
        if (e.key === 'Escape' && !editor.hidden) {
            closeEditor();
        }
    });

    statusBtns.forEach(function (b) {
        b.addEventListener('click', function () {
            setChosenStatus(b.getAttribute('data-value'));
        });
    });
    saveBtn.addEventListener('click', save);
    cancelBtn.addEventListener('click', closeEditor);
})();
