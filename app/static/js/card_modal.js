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

    var lastFocused = null;

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

    function populate(data) {
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
    }

    function loadCard(cardId) {
        showLoading();
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

    // Delegate clicks from any card button in the stacks.
    document.addEventListener('click', function (e) {
        var btn = e.target.closest ? e.target.closest('.stack-card-btn') : null;
        if (btn) {
            var cardId = btn.getAttribute('data-card-id');
            if (cardId) {
                loadCard(cardId);
            }
            return;
        }
        // Close when clicking the backdrop or an element marked data-close.
        var closer = e.target.closest ? e.target.closest('[data-close]') : null;
        if (closer && !modal.hidden) {
            closeModal();
        }
    });
})();
