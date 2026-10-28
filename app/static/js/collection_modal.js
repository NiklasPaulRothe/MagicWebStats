// Collection card popup. Clicking a collection card fetches
// /collection/card/<id> and shows (a) the decks that contain the card with
// their per-deck collection status and (b) a read-only printing slider. The
// slider clearly flags when the shown printing differs from the clicked one.
(function () {
    'use strict';

    var modal = document.getElementById('cc-modal');
    var grid = document.getElementById('collection-grid');
    if (!modal || !grid) {
        return;
    }

    var artEl = document.getElementById('cc-modal-art');
    var flagEl = document.getElementById('cc-modal-printing-flag');
    var sliderEl = document.getElementById('cc-modal-slider');
    var sliderPrev = document.getElementById('cc-slider-prev');
    var sliderNext = document.getElementById('cc-slider-next');
    var sliderLabel = document.getElementById('cc-slider-label');
    var titleEl = document.getElementById('cc-modal-title');
    var typeEl = document.getElementById('cc-modal-type');
    var textEl = document.getElementById('cc-modal-text');
    var decksBody = document.getElementById('cc-modal-decks-body');

    var lastFocused = null;
    // Printing slider state for the currently open card.
    var printings = [];       // [{id, set_code, set_name, image, current}]
    var currentIndex = 0;     // index into printings being viewed
    var clickedIndex = 0;     // index of the printing the user originally clicked

    // Status -> CSS modifier class, reusing the cc-coll-* vocabulary already on
    // the collection/deck pages so badge colors stay consistent.
    function statusClass(status) {
        return 'cc-deck-status cc-coll-' + (status || 'not_owned');
    }

    function clearEl(el) {
        while (el && el.firstChild) {
            el.removeChild(el.firstChild);
        }
    }

    function openModal() {
        lastFocused = document.activeElement;
        modal.hidden = false;
        document.body.classList.add('modal-open');
        document.addEventListener('keydown', onKeydown);
        var closeBtn = modal.querySelector('.cc-modal-close');
        if (closeBtn) { closeBtn.focus(); }
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
        if (e.key === 'Escape') { closeModal(); return; }
        if (modal.hidden) { return; }
        if (e.key === 'ArrowLeft') { step(-1); }
        else if (e.key === 'ArrowRight') { step(1); }
    }

    function showLoading() {
        titleEl.textContent = 'Loading\u2026';
        typeEl.textContent = '';
        clearEl(textEl);
        clearEl(decksBody);
        artEl.removeAttribute('src');
        artEl.alt = '';
        flagEl.hidden = true;
        sliderEl.hidden = true;
    }

    // Render oracle text with line breaks preserved. Inserted as textContent
    // (never innerHTML) so card text can't inject markup.
    function renderOracleText(container, text) {
        if (!text) { return; }
        text.split('\n').forEach(function (line) {
            var p = document.createElement('p');
            p.textContent = line;
            container.appendChild(p);
        });
    }

    // Render the card's text. For a double-faced card, show each face's name,
    // type and oracle text in order so both sides are visible.
    function renderFaces(faces, fallbackName, fallbackType) {
        clearEl(textEl);
        if (!faces || faces.length === 0) {
            return;
        }
        if (faces.length === 1) {
            if (faces[0].type_line && faces[0].type_line !== fallbackType) {
                var t = document.createElement('div');
                t.className = 'cc-face-type';
                t.textContent = faces[0].type_line;
                textEl.appendChild(t);
            }
            renderOracleText(textEl, faces[0].oracle_text);
            return;
        }
        faces.forEach(function (face) {
            var block = document.createElement('div');
            block.className = 'cc-face-block';

            var h = document.createElement('h4');
            h.className = 'cc-face-name';
            h.textContent = face.mana_cost
                ? (face.name + '  ' + face.mana_cost) : face.name;
            block.appendChild(h);

            if (face.type_line) {
                var ft = document.createElement('div');
                ft.className = 'cc-face-type';
                ft.textContent = face.type_line;
                block.appendChild(ft);
            }

            var body = document.createElement('div');
            renderOracleText(body, face.oracle_text);
            block.appendChild(body);

            textEl.appendChild(block);
        });
    }

    // Render the printing at currentIndex: swap art, update the slider label,
    // and flag clearly when it's not the printing the user clicked.
    function renderPrinting() {
        if (!printings.length) { return; }
        var p = printings[currentIndex];
        if (p.image) {
            artEl.src = p.image;
            artEl.alt = (titleEl.textContent || '') + ' \u2014 ' + (p.set_name || p.set_code || '');
            artEl.style.display = '';
        } else {
            artEl.removeAttribute('src');
            artEl.style.display = 'none';
        }

        var setText = (p.set_code || '').toUpperCase();
        if (p.set_name) { setText += ' \u00b7 ' + p.set_name; }
        var position = (currentIndex + 1) + ' / ' + printings.length;
        sliderLabel.textContent = setText + '  (' + position + ')';

        // Flag + outline when viewing anything other than the clicked printing.
        var isClicked = (currentIndex === clickedIndex);
        flagEl.hidden = isClicked;
        artEl.classList.toggle('is-other-printing', !isClicked);
    }

    function step(delta) {
        if (printings.length <= 1) { return; }
        currentIndex = (currentIndex + delta + printings.length) % printings.length;
        renderPrinting();
    }

    function renderDecks(decks) {
        clearEl(decksBody);
        if (!decks || decks.length === 0) {
            var none = document.createElement('p');
            none.className = 'cc-modal-decks-empty';
            none.textContent = 'This card is not in any of your decks.';
            decksBody.appendChild(none);
            return;
        }
        var list = document.createElement('ul');
        list.className = 'cc-deck-list';
        decks.forEach(function (d) {
            var li = document.createElement('li');
            li.className = 'cc-deck-row';

            var name = document.createElement('a');
            name.className = 'cc-deck-name';
            name.href = '/decks/overview/' + encodeURIComponent(d.deck_id);
            name.textContent = d.deck_name + (d.count > 1 ? ' (x' + d.count + ')' : '');
            li.appendChild(name);

            var meta = document.createElement('span');
            meta.className = 'cc-deck-meta';
            // Show the printing this deck uses, flagging when it differs from
            // the clicked one.
            var setText = (d.set_code || '').toUpperCase();
            if (!d.same_printing && setText) {
                setText += ' \u2260';  // not-equal mark: a different printing
            }
            meta.textContent = setText;
            if (!d.same_printing) {
                meta.classList.add('is-other-printing');
                meta.title = 'This deck uses a different printing';
            }
            li.appendChild(meta);

            var badge = document.createElement('span');
            badge.className = statusClass(d.status);
            badge.textContent = d.status_label || d.status;
            li.appendChild(badge);

            list.appendChild(li);
        });
        decksBody.appendChild(list);
    }

    function populate(data) {
        titleEl.textContent = data.name || '';
        typeEl.textContent = data.type_line || '';

        renderFaces(data.faces, data.name, data.type_line);

        printings = data.printings || [];
        // The clicked printing is the one flagged current by the server.
        clickedIndex = 0;
        for (var i = 0; i < printings.length; i++) {
            if (printings[i].current) { clickedIndex = i; break; }
        }
        currentIndex = clickedIndex;

        // Only show the slider when there's more than one printing to browse.
        sliderEl.hidden = printings.length <= 1;
        if (printings.length) {
            renderPrinting();
        } else if (data.image) {
            artEl.src = data.image;
            artEl.alt = data.name || '';
            flagEl.hidden = true;
        }

        renderDecks(data.decks);
    }

    function loadCard(cardId) {
        showLoading();
        openModal();
        fetch('/collection/card/' + encodeURIComponent(cardId), {
            headers: { 'Accept': 'application/json' }
        })
            .then(function (resp) {
                var ctype = resp.headers.get('content-type') || '';
                if (ctype.indexOf('application/json') === -1) {
                    throw new Error('Unexpected server response (HTTP ' + resp.status + ').');
                }
                return resp.json().then(function (data) {
                    if (!resp.ok || !data.ok) {
                        throw new Error((data && data.message) || ('HTTP ' + resp.status));
                    }
                    return data;
                });
            })
            .then(populate)
            .catch(function (err) {
                titleEl.textContent = 'Could not load card';
                typeEl.textContent = '';
                clearEl(decksBody);
                var p = document.createElement('p');
                p.className = 'cc-modal-decks-empty';
                p.textContent = String(err.message || err);
                decksBody.appendChild(p);
            });
    }

    // Open on click of any collection card that has a resolved card id.
    grid.addEventListener('click', function (e) {
        var card = e.target.closest ? e.target.closest('.collection-card') : null;
        if (!card) { return; }
        var cardId = card.getAttribute('data-card-id');
        if (cardId) {
            loadCard(cardId);
        }
    });

    if (sliderPrev) { sliderPrev.addEventListener('click', function () { step(-1); }); }
    if (sliderNext) { sliderNext.addEventListener('click', function () { step(1); }); }

    // Close on backdrop / close-button click.
    modal.addEventListener('click', function (e) {
        var closer = e.target.closest ? e.target.closest('[data-cc-close]') : null;
        if (closer && !modal.hidden) {
            closeModal();
        }
    });
})();
