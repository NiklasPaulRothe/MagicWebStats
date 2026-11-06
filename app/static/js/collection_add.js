/* collection_add.js — "Add card" dialog on the collection page.
 *
 * Step 1: card name with the shared autocomplete (/api/cards/autocomplete).
 * Step 2: printings of that name (GET data-printings-url?name=…) as an image
 *         grid with the edition name below; picking one advances.
 * Step 3: amount / finish / language, then POST data-add-url (JSON, CSRF via
 *         X-CSRFToken). On success the page reloads so the grid, totals and
 *         flash message come from the server.
 */
(function () {
    'use strict';

    var modal = document.getElementById('ca-modal');
    var openBtn = document.getElementById('ca-open');
    if (!modal || !openBtn) { return; }

    var nameInput = document.getElementById('ca-name');
    var list = document.getElementById('ca-printings');
    var hint = document.getElementById('ca-printing-hint');
    var countInput = document.getElementById('ca-count');
    var finishSel = document.getElementById('ca-finish');
    var langSel = document.getElementById('ca-language');
    var saveBtn = document.getElementById('ca-save');
    var chosenImg = document.getElementById('ca-chosen-img');
    var chosenName = document.getElementById('ca-chosen-name');
    var chosenSet = document.getElementById('ca-chosen-set');

    var state = { step: 1, name: null, printing: null, loading: false };
    var lastFocus = null;

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function showError(step, msg) {
        var el = document.getElementById('ca-error-' + step);
        if (!el) { return; }
        el.textContent = msg || '';
        el.hidden = !msg;
    }

    function goTo(step) {
        state.step = step;
        modal.querySelectorAll('.ca-step').forEach(function (s) {
            s.hidden = s.getAttribute('data-step') !== String(step);
        });
        modal.querySelectorAll('[data-step-dot]').forEach(function (d) {
            var n = parseInt(d.getAttribute('data-step-dot'), 10);
            d.classList.toggle('is-active', n === step);
            d.classList.toggle('is-done', n < step);
        });
        [1, 2, 3].forEach(function (n) { showError(n, ''); });
        // Focus the first useful control of the step.
        var target = step === 1 ? nameInput
            : step === 2 ? list.querySelector('.ca-printing')
            : countInput;
        if (target) { setTimeout(function () { target.focus(); }, 0); }
    }

    function open() {
        lastFocus = document.activeElement;
        state = { step: 1, name: null, printing: null, loading: false };
        nameInput.value = '';
        list.innerHTML = '';
        countInput.value = '1';
        finishSel.selectedIndex = 0;
        langSel.selectedIndex = 0;
        modal.hidden = false;
        document.body.classList.add('ca-open');
        goTo(1);
    }

    function close() {
        modal.hidden = true;
        document.body.classList.remove('ca-open');
        if (lastFocus && lastFocus.focus) { lastFocus.focus(); }
    }

    /* ── Step 1 → 2: load printings ─────────────────────────────────────── */
    function loadPrintings() {
        var name = nameInput.value.trim();
        if (!name) { showError(1, 'Please enter a card name.'); return; }
        if (state.loading) { return; }
        state.loading = true;
        showError(1, '');
        var url = modal.getAttribute('data-printings-url') + '?name=' + encodeURIComponent(name);
        fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
            .then(function (r) {
                return r.json().then(function (data) {
                    if (!r.ok || !data.ok) { throw new Error(data.message || 'Could not load printings.'); }
                    return data;
                });
            })
            .then(function (data) {
                state.name = data.name;
                renderPrintings(data.printings);
                goTo(2);
            })
            .catch(function (err) { showError(1, err.message); })
            .finally(function () { state.loading = false; });
    }

    function renderPrintings(printings) {
        list.innerHTML = '';
        hint.textContent = 'Choose the printing of ' + state.name + ' (' + printings.length + ')';
        printings.forEach(function (p) {
            var li = document.createElement('li');
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ca-printing';
            btn.setAttribute('role', 'option');
            btn.setAttribute('aria-label', p.set_name + (p.released_at ? ', ' + p.released_at.slice(0, 4) : ''));

            if (p.image) {
                var img = document.createElement('img');
                img.className = 'ca-printing-img';
                img.src = p.image;
                img.alt = '';
                img.loading = 'lazy';
                btn.appendChild(img);
            } else {
                var ph = document.createElement('span');
                ph.className = 'ca-printing-img ca-printing-ph';
                ph.textContent = p.name;
                btn.appendChild(ph);
            }
            var label = document.createElement('span');
            label.className = 'ca-printing-set';
            label.textContent = p.set_name;
            btn.appendChild(label);
            var meta = document.createElement('span');
            meta.className = 'ca-printing-meta';
            meta.textContent = (p.set_code || '').toUpperCase() + (p.released_at ? ' \u00b7 ' + p.released_at.slice(0, 4) : '');
            btn.appendChild(meta);

            btn.addEventListener('click', function () { choosePrinting(p); });
            li.appendChild(btn);
            list.appendChild(li);
        });
    }

    /* ── Step 2 → 3 ──────────────────────────────────────────────────────── */
    function choosePrinting(p) {
        state.printing = p;
        chosenImg.src = p.image || '';
        chosenImg.hidden = !p.image;
        chosenName.textContent = p.name;
        chosenSet.textContent = p.set_name + ' (' + (p.set_code || '').toUpperCase() + ')';
        goTo(3);
    }

    /* ── Step 3: save ────────────────────────────────────────────────────── */
    function save() {
        if (!state.printing || state.loading) { return; }
        var count = parseInt(countInput.value, 10);
        var max = parseInt(countInput.getAttribute('max'), 10) || 999;
        if (!count || count < 1 || count > max || String(count) !== countInput.value.trim()) {
            showError(3, 'Amount must be a whole number between 1 and ' + max + '.');
            countInput.focus();
            return;
        }
        state.loading = true;
        saveBtn.disabled = true;
        fetch(modal.getAttribute('data-add-url'), {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken()
            },
            body: JSON.stringify({
                card_id: state.printing.id,
                count: count,
                finish: finishSel.value,
                language: langSel.value
            })
        })
            .then(function (r) {
                return r.json().then(function (data) {
                    if (!r.ok || !data.ok) { throw new Error(data.message || 'The card could not be added.'); }
                    return data;
                });
            })
            .then(function () { window.location.reload(); })
            .catch(function (err) {
                showError(3, err.message);
                state.loading = false;
                saveBtn.disabled = false;
            });
    }

    /* ── Wiring ──────────────────────────────────────────────────────────── */
    if (typeof initAutocomplete === 'function') {
        // Picking a suggestion goes straight to the printings.
        initAutocomplete(nameInput, { onSelect: function () { loadPrintings(); } });
    }

    openBtn.addEventListener('click', open);
    document.getElementById('ca-next-1').addEventListener('click', loadPrintings);
    saveBtn.addEventListener('click', save);

    nameInput.addEventListener('keydown', function (e) {
        // Enter with the dropdown closed = Next (the autocomplete handles
        // Enter itself while a suggestion is highlighted).
        if (e.key === 'Enter' && nameInput.getAttribute('aria-expanded') !== 'true') {
            e.preventDefault();
            loadPrintings();
        }
    });
    countInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
    });

    modal.addEventListener('click', function (e) {
        if (e.target.closest('[data-ca-close]')) { close(); return; }
        var back = e.target.closest('[data-ca-back]');
        if (back) { goTo(parseInt(back.getAttribute('data-ca-back'), 10)); }
    });
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape' || modal.hidden) { return; }
        // Let the autocomplete close its own dropdown first.
        if (nameInput.getAttribute('aria-expanded') === 'true') { return; }
        e.preventDefault();
        close();
    });

    /* ── Import: confirm before replacing the whole collection ──────────── */
    var importForm = document.getElementById('collection-import-form');
    if (importForm) {
        importForm.addEventListener('submit', function (e) {
            var mode = importForm.querySelector('input[name="mode"]:checked');
            var total = parseInt(importForm.getAttribute('data-total-cards'), 10) || 0;
            if (mode && mode.value === 'replace' && total > 0 &&
                !window.confirm('Replace your whole collection (' + total + ' cards) with this file?\n\n' +
                                'Choose "Add to collection" to keep your current cards.')) {
                e.preventDefault();
            }
        });
    }
})();
