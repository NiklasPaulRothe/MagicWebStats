// Card popup for the deck overview. Clicking a card fetches its detail from
// /decks/card/<id> and renders image + readable text + rulings in a modal.
(function () {
    'use strict';

    var modal = document.getElementById('card-modal');
    if (!modal) {
        return;
    }

    var imageEl = document.getElementById('card-modal-image');
    var titleEl = document.getElementById('card-modal-title');
    var typeEl = document.getElementById('card-modal-type');
    var textEl = document.getElementById('card-modal-text');
    var rulingsSection = document.getElementById('card-modal-rulings');
    var rulingsBody = document.getElementById('card-modal-rulings-body');
    var printingBtn = document.getElementById('card-modal-printing-btn');
    var printingPicker = document.getElementById('card-printing-picker');
    var printingList = document.getElementById('card-printing-list');
    var printingTitle = document.getElementById('card-printing-title');
    var printingBack = document.getElementById('card-printing-back');
    var modalBody = document.getElementById('card-modal-body');

    var lastFocused = null;
    var deckId = modal.getAttribute('data-deck-id') || '';
    // The card currently shown, and the stack button it was opened from, so we
    // can update that button's image in place after a printing change.
    var currentCardId = null;
    var currentTriggerBtn = null;

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function deckBase() {
        // /decks/ prefix, shared by the card/printing endpoints.
        var marker = '/decks/';
        var idx = window.location.pathname.indexOf(marker);
        if (idx !== -1) {
            return window.location.pathname.slice(0, idx + marker.length);
        }
        return '/decks/';
    }

    function buildBase() {
        // Prefer the data endpoint path relative to the decks blueprint. The
        // overview lives at /decks/overview/<id>, so /decks/card/<id> is a
        // sibling; build it from the current path's /decks prefix.
        var marker = '/decks/';
        var idx = window.location.pathname.indexOf(marker);
        if (idx !== -1) {
            return window.location.pathname.slice(0, idx + marker.length) + 'card/';
        }
        return '/decks/card/';
    }

    var cardBase = buildBase();

    function clearText(el) {
        while (el.firstChild) {
            el.removeChild(el.firstChild);
        }
    }

    // Render oracle text with paragraph breaks preserved. Text is inserted as
    // textContent (never innerHTML) so card text can't inject markup.
    function renderOracleText(container, text) {
        clearText(container);
        if (!text) {
            return;
        }
        text.split('\n').forEach(function (line) {
            var p = document.createElement('p');
            p.textContent = line;
            container.appendChild(p);
        });
    }

    function renderFaces(faces, fallbackText) {
        clearText(textEl);
        // Single-face (or missing faces): just show the card-level oracle text.
        if (!faces || faces.length <= 1) {
            renderOracleText(textEl, (faces && faces[0] && faces[0].oracle_text) || fallbackText);
            return;
        }
        // Multi-face: show each face's name, type and text in sequence.
        faces.forEach(function (face) {
            var block = document.createElement('div');
            block.className = 'card-face-block';

            var h = document.createElement('h4');
            h.className = 'card-face-name';
            h.textContent = face.mana_cost ? (face.name + '  ' + face.mana_cost) : face.name;
            block.appendChild(h);

            if (face.type_line) {
                var t = document.createElement('div');
                t.className = 'card-face-type';
                t.textContent = face.type_line;
                block.appendChild(t);
            }

            var body = document.createElement('div');
            renderOracleText(body, face.oracle_text);
            block.appendChild(body);

            textEl.appendChild(block);
        });
    }

    function renderRulings(rulings) {
        clearText(rulingsBody);
        if (!rulings || rulings.length === 0) {
            var none = document.createElement('p');
            none.className = 'card-modal-rulings-empty';
            none.textContent = 'No rulings available.';
            rulingsBody.appendChild(none);
            return;
        }
        var list = document.createElement('ul');
        rulings.forEach(function (ruling) {
            var li = document.createElement('li');
            if (ruling.published_at) {
                var date = document.createElement('span');
                date.className = 'card-ruling-date';
                date.textContent = ruling.published_at;
                li.appendChild(date);
            }
            var comment = document.createElement('span');
            comment.className = 'card-ruling-comment';
            comment.textContent = ruling.comment;
            li.appendChild(comment);
            list.appendChild(li);
        });
        rulingsBody.appendChild(list);
    }

    function openModal() {
        lastFocused = document.activeElement;
        modal.hidden = false;
        document.body.classList.add('modal-open');
        document.addEventListener('keydown', onKeydown);
        var closeBtn = modal.querySelector('.card-modal-close');
        if (closeBtn) {
            closeBtn.focus();
        }
    }

    function closeModal() {
        modal.hidden = true;
        document.body.classList.remove('modal-open');
        document.removeEventListener('keydown', onKeydown);
        if (lastFocused && typeof lastFocused.focus === 'function') {
            lastFocused.focus();
        }
    }

    function onKeydown(e) {
        if (e.key === 'Escape') {
            closeModal();
        }
    }

    function showLoading() {
        titleEl.textContent = 'Loading\u2026';
        typeEl.textContent = '';
        clearText(textEl);
        clearText(rulingsBody);
        imageEl.src = '';
        imageEl.alt = '';
    }

    // Picker mode replaces the whole dialog content with the printing grid;
    // card mode shows the normal image + text + rulings view.
    function enterPickerMode() {
        modalBody.hidden = true;
        printingPicker.hidden = false;
        loadPrintings();
    }

    function exitPickerMode() {
        printingPicker.hidden = true;
        clearText(printingList);
        modalBody.hidden = false;
    }

    function populate(data) {
        currentCardId = data.id || null;
        titleEl.textContent = data.name || '';
        typeEl.textContent = data.type_line || '';

        // Use the front face image when available, else nothing.
        var frontImage = (data.faces && data.faces[0] && data.faces[0].image) || null;
        if (frontImage) {
            imageEl.src = frontImage;
            imageEl.alt = data.name || '';
            imageEl.style.display = '';
        } else {
            imageEl.removeAttribute('src');
            imageEl.alt = '';
            imageEl.style.display = 'none';
        }

        renderFaces(data.faces, data.oracle_text);
        renderRulings(data.rulings);

        // The printing button only makes sense when we know the deck and the
        // card is actually in it (opened from a stack card).
        var canChange = !!(deckId && currentTriggerBtn && currentCardId);
        printingBtn.hidden = !canChange;
    }

    function loadCard(cardId, triggerBtn) {
        currentTriggerBtn = triggerBtn || null;
        showLoading();
        printingBtn.hidden = true;
        exitPickerMode();
        openModal();
        fetch(cardBase + encodeURIComponent(cardId), {
            headers: { 'Accept': 'application/json' }
        })
            .then(function (resp) {
                if (!resp.ok) {
                    throw new Error('HTTP ' + resp.status);
                }
                return resp.json();
            })
            .then(function (data) {
                if (!data || !data.ok) {
                    throw new Error('Card not found');
                }
                populate(data);
            })
            .catch(function (err) {
                titleEl.textContent = 'Could not load card';
                clearText(textEl);
                var p = document.createElement('p');
                p.textContent = String(err.message || err);
                textEl.appendChild(p);
                clearText(rulingsBody);
            });
    }

    function renderPrintings(printings) {
        clearText(printingList);
        if (!printings || printings.length === 0) {
            var none = document.createElement('p');
            none.className = 'card-printing-empty';
            none.textContent = 'No printings available.';
            printingList.appendChild(none);
            return;
        }
        printings.forEach(function (p) {
            var item = document.createElement('button');
            item.type = 'button';
            item.className = 'card-printing-option' + (p.current ? ' is-current' : '');
            item.setAttribute('data-printing-id', p.id);
            item.title = p.set_name || p.set_code || '';

            if (p.image) {
                var img = document.createElement('img');
                img.src = p.image;
                img.alt = p.set_name || p.set_code || '';
                img.loading = 'lazy';
                item.appendChild(img);
            }
            var label = document.createElement('span');
            label.className = 'card-printing-set';
            label.textContent = (p.set_code || '').toUpperCase();
            item.appendChild(label);

            printingList.appendChild(item);
        });
    }

    function loadPrintings() {
        if (!deckId || !currentCardId) {
            return;
        }
        if (printingTitle) {
            printingTitle.textContent = titleEl.textContent
                ? ('Choose a printing \u2014 ' + titleEl.textContent)
                : 'Choose a printing';
        }
        clearText(printingList);
        var loading = document.createElement('p');
        loading.className = 'card-printing-empty';
        loading.textContent = 'Loading printings\u2026';
        printingList.appendChild(loading);

        var url = deckBase() + encodeURIComponent(deckId) + '/card/' +
            encodeURIComponent(currentCardId) + '/printings';
        fetch(url, { headers: { 'Accept': 'application/json' } })
            .then(function (resp) {
                if (!resp.ok) { throw new Error('HTTP ' + resp.status); }
                return resp.json();
            })
            .then(function (data) {
                if (!data || !data.ok) { throw new Error('Could not load printings'); }
                renderPrintings(data.printings);
            })
            .catch(function (err) {
                clearText(printingList);
                var p = document.createElement('p');
                p.className = 'card-printing-empty';
                p.textContent = String(err.message || err);
                printingList.appendChild(p);
            });
    }

    function selectPrinting(printingId) {
        if (!deckId || !currentCardId || !printingId) {
            return;
        }
        var url = deckBase() + encodeURIComponent(deckId) + '/card/' +
            encodeURIComponent(currentCardId) + '/printing';
        fetch(url, {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken()
            },
            body: JSON.stringify({ printing_id: printingId })
        })
            .then(function (resp) {
                if (!resp.ok) { throw new Error('HTTP ' + resp.status); }
                return resp.json();
            })
            .then(function (data) {
                if (!data || !data.ok) { throw new Error('Could not change printing'); }
                // Update the originating stack card image + id to the new
                // printing, re-point state, then return to the card view
                // showing the freshly chosen printing.
                if (data.image && currentTriggerBtn) {
                    var stackImg = currentTriggerBtn.querySelector('.stack-card-img');
                    if (stackImg && stackImg.tagName === 'IMG') {
                        stackImg.src = data.image;
                    }
                }
                if (currentTriggerBtn) {
                    currentTriggerBtn.setAttribute('data-card-id', data.card_id);
                }
                currentCardId = data.card_id;
                // Reload the full card detail for the new printing, then flip
                // back from the picker to the card view.
                loadCard(data.card_id, currentTriggerBtn);
            })
            .catch(function (err) {
                clearText(printingList);
                var p = document.createElement('p');
                p.className = 'card-printing-empty';
                p.textContent = String(err.message || err);
                printingList.appendChild(p);
            });
    }

    printingBtn.addEventListener('click', function () {
        enterPickerMode();
    });

    if (printingBack) {
        printingBack.addEventListener('click', function () {
            exitPickerMode();
        });
    }

    // Delegate clicks from any card button in the stacks.
    document.addEventListener('click', function (e) {
        var btn = e.target.closest ? e.target.closest('.stack-card-btn') : null;
        if (btn) {
            var cardId = btn.getAttribute('data-card-id');
            if (cardId) {
                loadCard(cardId, btn);
            }
            return;
        }
        // Printing option chosen.
        var opt = e.target.closest ? e.target.closest('.card-printing-option') : null;
        if (opt) {
            selectPrinting(opt.getAttribute('data-printing-id'));
            return;
        }
        // Close when clicking the backdrop or an element marked data-close.
        var closer = e.target.closest ? e.target.closest('[data-close]') : null;
        if (closer && !modal.hidden) {
            closeModal();
        }
    });
})();
