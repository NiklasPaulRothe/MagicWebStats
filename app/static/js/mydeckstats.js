/* mydeckstats.js — My Deck Stats card grid.
 *
 * Config comes from data-* on #my-deck-stats (player id/name, owner flag,
 * reactivate permission, initial view, dearchive URL ending in /0).
 * Active decks:   GET /api/userdecks/<id>
 * Archived decks: GET /api/userdecks/archive/<id>  (fetched on first use)
 * Sorting/searching run client-side over the loaded list. Empty values always
 * sort last, whatever the sort. Presentation is neutral: plain numbers, no
 * colouring or ranking.
 */
(function () {
    'use strict';

    const root = document.getElementById('my-deck-stats');
    if (!root) return;

    const playerId = root.dataset.playerId;
    const playerName = root.dataset.playerName;
    const isOwner = root.dataset.owner === 'true';
    const canReactivate = root.dataset.canReactivate === 'true';
    const dearchiveUrl = root.dataset.dearchiveUrl;  // ".../dearchive/0"
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    const DEFAULT_IMG = '/static/img/default_commander.png';

    const grid = document.getElementById('mds-grid');
    const empty = document.getElementById('mds-empty');
    const summary = document.getElementById('mds-summary');
    const sortSelect = document.getElementById('mds-sort');
    const search = document.getElementById('mds-search');
    const viewBtns = Array.from(root.querySelectorAll('.seg__btn[data-view]'));

    const cache = { active: null, archived: null };
    let view = root.dataset.view === 'archived' ? 'archived' : 'active';

    /* ── Helpers ─────────────────────────────────────────────────────────── */
    function esc(v) {
        if (v == null) return '';
        return String(v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }
    const dash = '\u2013';
    const fmtNum = (v) => (v == null ? dash : String(Math.round(Number(v) * 10) / 10));
    const fmtPct = (v) => (v == null ? dash : `${Math.round(Number(v) * 10) / 10}%`);
    // Avg win turn only counts when there were wins with a recorded turn count.
    const avgTurn = (d) => (d.win_turns_count ? d.avg_win_turns : null);

    /* Sort definitions: [value getter, direction]. Null/empty sorts last. */
    const SORTS = {
        games:         [(d) => d.games, 'desc'],
        last_played:   [(d) => d.last_played_iso, 'desc'],
        name:          [(d) => (d.name || '').toLowerCase(), 'asc'],
        winrate:       [(d) => d.winrate_pct, 'desc'],
        avg_win_turns: [avgTurn, 'asc'],
    };

    function sortDecks(list, key) {
        const [get, dir] = SORTS[key] || SORTS.games;
        const sign = dir === 'asc' ? 1 : -1;
        return list.slice().sort((a, b) => {
            const va = get(a), vb = get(b);
            const ea = va == null || va === '', eb = vb == null || vb === '';
            if (ea || eb) {
                if (ea !== eb) return ea ? 1 : -1;   // empty last
            } else if (va !== vb) {
                const c = typeof va === 'number' && typeof vb === 'number'
                    ? va - vb : String(va).localeCompare(String(vb));
                if (c !== 0) return sign * c;
            }
            return (a.name || '').localeCompare(b.name || '');  // stable tie-break
        });
    }

    function matches(d, q) {
        if (!q) return true;
        const hay = [d.name, d.commander, ...(d.tags || [])].join(' ').toLowerCase();
        return hay.includes(q);
    }

    /* ── Rendering ───────────────────────────────────────────────────────── */
    function renderSummary(list) {
        const n = list.length;
        const label = view === 'archived' ? 'archived' : 'active';
        if (!n) {
            summary.textContent = `No ${label} decks`;
            return;
        }
        const games = list.reduce((s, d) => s + (d.games || 0), 0);
        const wins = list.reduce((s, d) => s + (d.wins || 0), 0);
        const last = list.map((d) => d.last_played_iso).filter(Boolean).sort().pop();
        const parts = [
            `${n} ${label} deck${n === 1 ? '' : 's'}`,
            `${games} game${games === 1 ? '' : 's'}`,
            `${wins} win${wins === 1 ? '' : 's'}`,
        ];
        if (games) parts.push(`${Math.round((wins / games) * 1000) / 10}% winrate`);
        if (last) parts.push(`last game ${last}`);
        summary.textContent = parts.join(' \u00b7 ');
    }

    function cardHtml(d, totalGames) {
        const url = `/decks/show/${encodeURIComponent(d.name)}`;
        const share = totalGames ? (d.games || 0) / totalGames * 100 : 0;
        const shareTxt = `${Math.round(share * 10) / 10}%`;
        const pips = (d.color_imgs || [])
            .map((src) => `<img src="${esc(src)}" class="mds-pip" alt="">`).join('');
        const tags = d.tags || [];
        const tagHtml = tags.slice(0, 3).map((t) => `<span class="mds-tag">${esc(t)}</span>`).join('')
            + (tags.length > 3 ? `<span class="mds-tag" title="${esc(tags.slice(3).join(', '))}">+${tags.length - 3}</span>` : '');
        const commander = d.decklist
            ? `<a class="mds-card__commander mds-raise" href="${esc(d.decklist)}" target="_blank" rel="noopener noreferrer" title="Open decklist">${esc(d.commander)}</a>`
            : `<span class="mds-card__commander">${esc(d.commander)}</span>`;

        let action = '';
        if (view === 'active' && isOwner) {
            action = `<a class="mds-action mds-raise" href="/decks/edit/${encodeURIComponent(d.name)}"
                         title="Edit deck" aria-label="Edit ${esc(d.name)}">\u270E</a>`;
        } else if (view === 'archived' && canReactivate && d.id != null) {
            action = `<form method="POST" class="mds-raise" action="${esc(dearchiveUrl.replace(/0$/, String(d.id)))}">
                          <input type="hidden" name="csrf_token" value="${esc(csrfToken)}">
                          <input type="hidden" name="player_name" value="${esc(playerName)}">
                          <input type="hidden" name="return_to" value="mydeckstats">
                          <button type="submit" class="mds-reactivate">Reactivate</button>
                      </form>`;
        }

        return `
        <article class="mds-card${view === 'archived' ? ' mds-card--archived' : ''}">
            <img class="mds-card__art" src="${esc(d.image_uri || DEFAULT_IMG)}" alt="" loading="lazy">
            <div class="mds-card__head">
                <h2 class="mds-card__name"><a class="mds-card__link" href="${url}">${esc(d.name)}</a></h2>
                ${commander}
                <div class="mds-card__pips">${pips}</div>
                ${tagHtml ? `<div class="mds-card__tags">${tagHtml}</div>` : ''}
            </div>
            <dl class="mds-card__stats">
                <div><dt>Games</dt><dd>${d.games ?? 0}</dd></div>
                <div><dt>Wins</dt><dd>${d.wins ?? 0}</dd></div>
                <div><dt>Winrate</dt><dd>${fmtPct(d.winrate_pct)}</dd></div>
                <div><dt>Avg win T.</dt><dd>${fmtNum(avgTurn(d))}</dd></div>
            </dl>
            <div class="mds-card__share">
                <span>Share of your games</span>
                <span class="mds-share" role="img" aria-label="${shareTxt} of games">
                    <span class="mds-share__fill" style="width:${Math.min(100, share).toFixed(1)}%"></span>
                </span>
                <span class="mds-share__pct">${shareTxt}</span>
            </div>
            <div class="mds-card__foot">
                <span>${d.last_played_iso ? `Last played ${esc(d.last_played_iso)}` : 'Not played yet'}</span>
                ${action}
            </div>
        </article>`;
    }

    function render() {
        const all = cache[view];
        if (!all) return;
        renderSummary(all);
        // Share is relative to ALL decks in this view, not just the search hits.
        const totalGames = all.reduce((s, d) => s + (d.games || 0), 0);
        const q = search.value.trim().toLowerCase();
        const list = sortDecks(all.filter((d) => matches(d, q)), sortSelect.value);

        grid.innerHTML = list.map((d) => cardHtml(d, totalGames)).join('');
        if (!list.length) {
            empty.textContent = all.length
                ? 'No decks match your search.'
                : (view === 'archived' ? 'No archived decks.' : 'No active decks yet.');
        }
        empty.hidden = list.length > 0;
    }

    /* ── Data loading ────────────────────────────────────────────────────── */
    async function load(which) {
        if (cache[which]) return;
        const url = which === 'archived'
            ? `/api/userdecks/archive/${encodeURIComponent(playerId)}`
            : `/api/userdecks/${encodeURIComponent(playerId)}`;
        const resp = await fetch(url, { credentials: 'same-origin' });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        cache[which] = await resp.json();
    }

    async function show(which) {
        view = which;
        viewBtns.forEach((b) => {
            const on = b.dataset.view === which;
            b.classList.toggle('active', on);
            b.setAttribute('aria-pressed', String(on));
        });
        // Keep the view in the URL so reload / back returns to it.
        const u = new URL(window.location.href);
        if (which === 'archived') u.searchParams.set('view', 'archived');
        else u.searchParams.delete('view');
        history.replaceState(null, '', u);

        if (!cache[which]) {
            summary.textContent = 'Loading\u2026';
            grid.innerHTML = '';
            empty.hidden = true;
        }
        try {
            await load(which);
            if (view === which) render();   // ignore stale responses
        } catch (err) {
            console.error('Failed to load decks:', err);
            summary.textContent = '';
            grid.innerHTML = '';
            empty.textContent = 'Daten konnten nicht geladen werden.';
            empty.hidden = false;
        }
    }

    viewBtns.forEach((b) => b.addEventListener('click', () => { if (b.dataset.view !== view) show(b.dataset.view); }));
    sortSelect.addEventListener('change', render);
    search.addEventListener('input', render);

    show(view);
})();
