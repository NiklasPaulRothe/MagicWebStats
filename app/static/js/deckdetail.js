/* deckdetail.js — Deck detail page behaviour.
 * Reads its configuration from data-* attributes on #deck-detail:
 *   data-deckname, data-rework, data-patch (ISO dates or ''),
 *   data-url-add, data-url-progress, data-url-delete (the latter two end in /0).
 * Handles: Stats/Achievements view toggle, range filters (performance + private
 * averages, kept in sync), and achievement add/progress/delete.
 */
(function () {
    'use strict';

    const root = document.getElementById('deck-detail');
    if (!root) return;

    const deckname = root.dataset.deckname;
    const lastRework = root.dataset.rework || null;
    const lastPatch = root.dataset.patch || null;
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : null;
    const csrfHeaders = csrfToken ? { 'X-CSRFToken': csrfToken, 'X-CSRF-Token': csrfToken } : {};
    const $ = (id) => document.getElementById(id);
    const withId = (url, id) => url.replace(/0$/, encodeURIComponent(id));

    /* ── Stats / Achievements view ──────────────────────────────────────── */
    const btnAch = $('btn-mode-achievements');
    const achView = $('dd-achievements-view');

    function showAchievements(show) {
        achView.hidden = !show;
        btnAch.classList.toggle('active', show);
        btnAch.setAttribute('aria-pressed', String(show));
    }
    btnAch?.addEventListener('click', () => showAchievements(achView.hidden));

    const pct = (v) => (typeof v === 'number' ? v + '%' : '\u2013');

    /* ── Personal per-game detail rows (collapsed by default) ───────────── */
    document.querySelectorAll('.dd-detail-toggle').forEach((btn) => {
        btn.addEventListener('click', () => {
            const row = document.getElementById(btn.getAttribute('aria-controls'));
            if (!row) return;
            const open = btn.getAttribute('aria-expanded') !== 'true';
            row.hidden = !open;
            btn.setAttribute('aria-expanded', String(open));
            btn.title = open ? 'Hide personal details' : 'Show personal details';
            const label = btn.querySelector('.sr-only');
            if (label) label.textContent = label.textContent.replace(open ? /^Show/ : /^Hide/, open ? 'Hide' : 'Show');
        });
    });

    /* ── Game history pagination (10 games per page) ─────────────────────── */
    const GAMES_PER_PAGE = 10;
    const gameBodies = Array.from(document.querySelectorAll('.dd-table tbody.dd-game'));
    const pager = $('dd-games-pager');
    if (pager && gameBodies.length > GAMES_PER_PAGE) {
        const totalPages = Math.ceil(gameBodies.length / GAMES_PER_PAGE);
        const prevBtn = pager.querySelector('[data-page="prev"]');
        const nextBtn = pager.querySelector('[data-page="next"]');
        const status = pager.querySelector('[data-role="status"]');
        const card = pager.closest('.dd-card');
        let page = 0;

        function renderPage() {
            const start = page * GAMES_PER_PAGE;
            const end = start + GAMES_PER_PAGE;
            gameBodies.forEach((tb, i) => { tb.hidden = i < start || i >= end; });
            status.textContent = `Games ${start + 1}\u2013${Math.min(end, gameBodies.length)} of ${gameBodies.length}`;
            prevBtn.disabled = page === 0;
            nextBtn.disabled = page >= totalPages - 1;
        }
        function go(delta) {
            page = Math.min(totalPages - 1, Math.max(0, page + delta));
            renderPage();
            // Keep the table header in view when the page height changes.
            if (card && card.getBoundingClientRect().top < 0) card.scrollIntoView({ block: 'start' });
        }
        prevBtn.addEventListener('click', () => go(-1));
        nextBtn.addEventListener('click', () => go(1));
        renderPage();
    }

    /* ── Range filters (performance + private averages) ─────────────────── */
    const perfBtns = { all: $('perf-filter-all'), rework: $('perf-filter-rework'), patch: $('perf-filter-patch') };
    const avgBtns = { all: $('avg-filter-all'), rework: $('avg-filter-rework'), patch: $('avg-filter-patch') };
    const perfInfo = $('perf-filter-info');
    const avgInfo = $('avg-filter-info');
    const hasAvgs = !!document.querySelector('[data-avg]');

    function setActive(key) {
        [perfBtns, avgBtns].forEach((group) => {
            Object.entries(group).forEach(([k, btn]) => btn?.classList.toggle('active', k === key));
        });
    }

    const setText = (sel, val) => {
        const el = document.querySelector(sel);
        if (el) el.textContent = val;
    };

    function updatePerf(data) {
        if (data.empty) {
            if (perfInfo) perfInfo.textContent = data.message || 'No data';
            return;
        }
        if (perfInfo) perfInfo.textContent = '';
        ['games', 'wins', 'avg_turns', 'median_turns'].forEach((key) => {
            setText(`[data-perf="${key}"]`, data[key] !== undefined ? data[key] : '\u2013');
        });
        setText('[data-perf="winrate"]', pct(data.winrate));
        setText('[data-perf="range"]',
            data.min_turns && data.max_turns ? data.min_turns + ' \u2013 ' + data.max_turns : '\u2013');

        [3, 4, 5].forEach((size) => {
            const s = data.by_size && data.by_size[String(size)];
            if (!s) return;
            setText(`[data-perf="size_${size}_games"]`, s.games);
            setText(`[data-perf="size_${size}_wins"]`, s.wins);
            setText(`[data-perf="size_${size}_winrate"]`, pct(s.winrate));
            setText(`[data-perf="size_${size}_avg_turns"]`, s.avg_turns);
            setText(`[data-perf="size_${size}_median_turns"]`, s.median_turns);
        });
    }

    function updateAvg(data) {
        if (data.empty) {
            if (avgInfo) avgInfo.textContent = data.message || 'No data';
            return;
        }
        if (avgInfo) avgInfo.textContent = `(${data.games_count} games)`;
        document.querySelectorAll('[data-avg]').forEach((el) => {
            const key = el.getAttribute('data-avg');
            el.textContent = data[key] !== undefined ? data[key] : '\u2013';
        });
    }

    async function load(kind, since, infoEl, apply) {
        let url = `/api/${kind}/${encodeURIComponent(deckname)}`;
        if (since) url += `?since=${since}`;
        if (infoEl) infoEl.textContent = 'Loading...';
        try {
            const resp = await fetch(url, { credentials: 'same-origin' });
            apply(await resp.json());
        } catch (e) {
            console.error(`Failed to load ${kind}:`, e);
            if (infoEl) infoEl.textContent = 'Error';
        }
    }

    function applyFilter(key, since) {
        setActive(key);
        load('deck-performance', since, perfInfo, updatePerf);
        if (hasAvgs) load('deck-participant-averages', since, avgInfo, updateAvg);
    }

    [perfBtns, avgBtns].forEach((group) => {
        group.all?.addEventListener('click', () => applyFilter('all', null));
        group.rework?.addEventListener('click', () => applyFilter('rework', lastRework));
        group.patch?.addEventListener('click', () => applyFilter('patch', lastPatch));
    });

    /* ── Achievements ───────────────────────────────────────────────────── */
    const overlay = $('add-achievement-overlay');
    const addForm = $('add-achievement-form');

    function openAddModal() {
        overlay.style.display = 'flex';
        setTimeout(() => $('ach-title')?.focus(), 0);
    }
    function closeAddModal() {
        overlay.style.display = 'none';
        addForm?.reset();
    }
    $('btn-add-achievement')?.addEventListener('click', openAddModal);
    $('btn-cancel-add')?.addEventListener('click', closeAddModal);
    overlay?.addEventListener('click', (e) => { if (e.target === overlay) closeAddModal(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay && overlay.style.display === 'flex') closeAddModal();
    });

    function createAchievementCard(a) {
        const card = document.createElement('div');
        card.className = 'achievement-card';
        card.setAttribute('data-achievement-id', a.id);
        const checks = Array.from({ length: a.amount || 0 }, (_, i) => `
            <label class="check" title="${i < (a.achieved || 0) ? 'erreicht' : 'offen'}">
                <input type="checkbox" class="achievement-check" ${i < (a.achieved || 0) ? 'checked' : ''}>
                <span></span>
            </label>`).join('');
        card.innerHTML = `
            <div class="achievement-header">
                <h4 class="achievement-title"></h4>
                <button type="button" class="dd-btn btn-ach-delete" title="Achievement löschen" aria-label="Achievement löschen">\u2715</button>
            </div>
            <p class="achievement-desc"></p>
            <div class="achievement-checks">${checks}</div>`;
        card.querySelector('.achievement-title').textContent = a.title || '';
        card.querySelector('.achievement-desc').textContent = a.description || '';
        return card;
    }

    function attachCardListeners(card) {
        card.setAttribute('data-prev-count', String(card.querySelectorAll('input.achievement-check:checked').length));
        card.addEventListener('change', (e) => {
            if (e.target && e.target.matches('input.achievement-check')) onChecksChanged(card);
        });
        card.querySelector('.btn-ach-delete')?.addEventListener('click', () => onDeleteAchievement(card));
    }

    addForm?.addEventListener('submit', (e) => {
        e.preventDefault();
        if (!addForm.titel.value.trim()) {
            addForm.titel.focus();
            return;
        }
        const body = new URLSearchParams(Array.from(new FormData(addForm).entries()));
        fetch(root.dataset.urlAdd, { method: 'POST', body, credentials: 'same-origin' })
            .then(async (r) => {
                const data = await r.json().catch(() => null);
                if (!r.ok || !data || !data.ok) throw new Error((data && data.message) || 'Speichern fehlgeschlagen');
                let grid = $('achievements-grid');
                if (!grid) {
                    grid = document.createElement('div');
                    grid.className = 'achievements-grid';
                    grid.id = 'achievements-grid';
                    const actions = document.querySelector('.achievements-actions');
                    actions?.parentNode?.insertBefore(grid, actions);
                    document.querySelector('.achievements-empty')?.remove();
                }
                const card = createAchievementCard(data.achievement);
                grid.appendChild(card);
                attachCardListeners(card);
                closeAddModal();
                showAchievements(true);
            })
            .catch((err) => {
                console.error('Failed to add achievement:', err);
                alert(err.message || 'Fehler beim Speichern.');
            });
    });

    function onChecksChanged(card) {
        const id = card.getAttribute('data-achievement-id');
        const checks = card.querySelectorAll('input.achievement-check');
        const desired = Array.from(checks).filter((c) => c.checked).length;
        fetch(withId(root.dataset.urlProgress, id), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...csrfHeaders },
            body: JSON.stringify({ achieved: desired }),
            credentials: 'same-origin',
        })
            .then(async (r) => {
                const data = await r.json().catch(() => ({}));
                if (!r.ok || !data.ok) throw new Error(data.message || 'Update failed');
                const accepted = data.achieved ?? desired;
                checks.forEach((c, idx) => { c.checked = idx < accepted; });
            })
            .catch((err) => {
                console.error('Failed to update achievement progress:', err);
                const prev = parseInt(card.getAttribute('data-prev-count') || '0', 10);
                checks.forEach((c, idx) => { c.checked = idx < prev; });
            })
            .finally(() => {
                card.setAttribute('data-prev-count',
                    String(Array.from(checks).filter((c) => c.checked).length));
            });
    }

    function onDeleteAchievement(card) {
        const id = card.getAttribute('data-achievement-id');
        if (!id || !confirm('Achievement wirklich löschen?')) return;
        fetch(withId(root.dataset.urlDelete, id), {
            method: 'POST',
            headers: csrfHeaders,
            credentials: 'same-origin',
        })
            .then(async (r) => {
                const data = await r.json().catch(() => null);
                if (!r.ok || !data || !data.ok) throw new Error((data && data.message) || 'Löschen fehlgeschlagen');
                card.remove();
                const grid = $('achievements-grid');
                if (grid && grid.children.length === 0) {
                    const p = document.createElement('p');
                    p.className = 'achievements-empty dd-muted';
                    p.textContent = 'Keine Achievements vorhanden.';
                    grid.parentNode.insertBefore(p, grid.nextSibling);
                }
            })
            .catch((err) => {
                console.error('Failed to delete achievement:', err);
                alert(err.message || 'Fehler beim Löschen.');
            });
    }

    document.querySelectorAll('.achievement-card').forEach(attachCardListeners);
})();
