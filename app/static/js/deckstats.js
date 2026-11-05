function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

let originalData = [];
let currentSort = { idx: null, asc: true, type: null };
// How many rows to render per page. Filtering + sorting always run over the
// FULL dataset; only the display is paged (25 / 50 / 100 per page).
let pageSize = 25;
let currentPage = 1;   // 1-based; the slice shown is page `currentPage`.
let lastFilteredCount = 0;

document.addEventListener('DOMContentLoaded', function () {
    fetch('/api/deck-data')
        .then(response => {
            if (!response.ok) throw new Error('HTTP ' + response.status);
            return response.json();
        })
        .then(data => {
            originalData = data;
            populateSpielerFilter('spieler-filter-dropdown', data);
            renderFilteredAndSortedTable();
        })
        .catch(err => {
            console.error('Failed to load deck data:', err);
            const tbody = document.querySelector('#deck-stats-table tbody');
            if (tbody) {
                const colCount = document.querySelectorAll('#deck-stats-table thead th').length;
                tbody.innerHTML = `<tr><td colspan="${colCount}">Daten konnten nicht geladen werden.</td></tr>`;
            }
        });

    document.getElementById('apply-min-spiele-filter').addEventListener('click', () => {
        currentPage = 1;
        renderFilteredAndSortedTable();
    });

    document.getElementById('reset-filters').addEventListener('click', () => {
        document.getElementById('min-spiele-filter').value = '';
        document.querySelectorAll('#spieler-filter-dropdown input[type="checkbox"]').forEach(cb => cb.checked = true);
        const toggleBtn = document.querySelector('#spieler-filter-dropdown .filter-toggle-all');
        if (toggleBtn) toggleBtn.textContent = 'Deselect All';
        currentSort = { idx: null, asc: true, type: null };
        currentPage = 1;
        renderFilteredAndSortedTable();
    });

    // Page-size control (25 / 50 / 100). Changing it resets to page 1.
    const pageSizeGroup = document.getElementById('page-size');
    if (pageSizeGroup) {
        pageSizeGroup.querySelectorAll('button[data-size]').forEach(btn => {
            btn.addEventListener('click', function () {
                pageSize = parseInt(this.getAttribute('data-size'), 10) || 25;
                currentPage = 1;
                pageSizeGroup.querySelectorAll('button').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                renderFilteredAndSortedTable();
            });
        });
    }

    // Prev / Next pagers (top and bottom both drive the same currentPage).
    document.querySelectorAll('.ptable-pager .pager__btn').forEach(btn => {
        btn.addEventListener('click', function () {
            const dir = this.getAttribute('data-page');
            const totalPages = Math.max(1, Math.ceil(lastFilteredCount / pageSize));
            if (dir === 'next' && currentPage < totalPages) currentPage++;
            else if (dir === 'prev' && currentPage > 1) currentPage--;
            else return;
            renderFilteredAndSortedTable();
        });
    });

    const filterBtn = document.getElementById('spieler-filter-btn');
    const filterDropdown = document.getElementById('spieler-filter-dropdown');

    filterBtn.addEventListener('click', function (event) {
        event.stopPropagation(); // prevent table header sort
        filterDropdown.style.display = filterDropdown.style.display === 'block' ? 'none' : 'block';
        const rect = filterBtn.getBoundingClientRect();
        filterDropdown.style.left = `${rect.left}px`;
        filterDropdown.style.top = `${rect.bottom}px`;
    });

    document.addEventListener('click', function (event) {
        if (!filterDropdown.contains(event.target) && event.target !== filterBtn) {
            filterDropdown.style.display = 'none';
        }
    });

    function populateSpielerFilter(filterId, data) {
        const dropdown = document.getElementById(filterId);
        dropdown.innerHTML = '';
        const uniquePlayers = [];

        data.forEach(item => {
            const playerName = item.player_name;
            if (!uniquePlayers.includes(playerName)) {
                uniquePlayers.push(playerName);
            }
        });

        uniquePlayers.sort();

        // Toggle All button
        const toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'filter-toggle-all';
        toggleBtn.textContent = 'Deselect All';
        dropdown.appendChild(toggleBtn);

        const separator = document.createElement('hr');
        separator.className = 'filter-separator';
        dropdown.appendChild(separator);

        // Player checkboxes
        uniquePlayers.forEach(playerName => {
            const label = document.createElement('label');
            label.className = 'filter-option';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = playerName;
            checkbox.checked = true;
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(' ' + playerName));
            dropdown.appendChild(label);
        });

        // Toggle All logic
        toggleBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            const checkboxes = dropdown.querySelectorAll('input[type="checkbox"]');
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);
            checkboxes.forEach(cb => cb.checked = !allChecked);
            toggleBtn.textContent = allChecked ? 'Select All' : 'Deselect All';
            currentPage = 1;
            renderFilteredAndSortedTable();
        });

        // Update toggle button text when individual checkboxes change
        dropdown.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('click', function (e) {
                e.stopPropagation();
                const checkboxes = dropdown.querySelectorAll('input[type="checkbox"]');
                const allChecked = Array.from(checkboxes).every(cb => cb.checked);
                if (allChecked) {
                    toggleBtn.textContent = 'Deselect All';
                } else {
                    toggleBtn.textContent = 'Select All';
                }
                currentPage = 1;
                renderFilteredAndSortedTable();
            });
        });
    }

    function renderFilteredAndSortedTable() {
        const minValue = parseInt(document.getElementById('min-spiele-filter').value, 10) || 0;

        const checkboxes = document.querySelectorAll('#spieler-filter-dropdown input[type="checkbox"]');
        const checkedPlayers = Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => cb.value);

        let filtered = originalData.filter(item => {
            return item.games >= minValue && checkedPlayers.includes(item.player_name);
        });

        if (currentSort.idx !== null) {
            const headers = document.querySelectorAll('th');
            const key = headers[currentSort.idx].getAttribute('data-key');
            filtered.sort((a, b) => {
                // Special sort for Color Identity: by count then by image URLs
                if (key === 'color_identity') {
                    const imgsA = Array.isArray(a.color_imgs) ? a.color_imgs : [];
                    const imgsB = Array.isArray(b.color_imgs) ? b.color_imgs : [];
                    const countDiff = imgsA.length - imgsB.length;
                    if (countDiff !== 0) return currentSort.asc ? countDiff : -countDiff;
                    const strA = imgsA.join('|');
                    const strB = imgsB.join('|');
                    return currentSort.asc ? strA.localeCompare(strB) : strB.localeCompare(strA);
                }
                // Empty values always sort LAST, regardless of direction. A
                // value is "empty" when null/undefined/"", when it's Elo 0
                // (rendered as "-"), or avg-win-turn with no counted wins ("-").
                let rawA = a[key], rawB = b[key];
                const ea = rawA === null || rawA === undefined || rawA === '' ||
                           (key === 'elo' && Number(rawA) === 0) ||
                           (key === 'avg_win_turns' && !a.win_turns_count);
                const eb = rawB === null || rawB === undefined || rawB === '' ||
                           (key === 'elo' && Number(rawB) === 0) ||
                           (key === 'avg_win_turns' && !b.win_turns_count);
                if (ea || eb) return ea === eb ? 0 : (ea ? 1 : -1);
                const valA = rawA, valB = rawB;
                if (currentSort.type === 'number') {
                    return currentSort.asc ? valA - valB : valB - valA;
                } else {
                    return currentSort.asc
                        ? valA.toString().localeCompare(valB)
                        : valB.toString().localeCompare(valA);
                }
            });
        }

        lastFilteredCount = filtered.length;
        const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
        // Clamp the current page into the valid range (e.g. after filtering
        // shrinks the result set below the current page).
        if (currentPage > totalPages) currentPage = totalPages;
        if (currentPage < 1) currentPage = 1;

        const start = (currentPage - 1) * pageSize;
        const pageRows = filtered.slice(start, start + pageSize);

        updateSortIndicators();
        populateTable('deck-stats-table', pageRows);
        updatePagers(filtered.length, totalPages, start, pageRows.length);
    }

    function updatePagers(total, totalPages, start, shown) {
        const from = total === 0 ? 0 : start + 1;
        const to = start + shown;
        const statusText = total > pageSize
            ? `${from}\u2013${to} of ${total} \u00b7 page ${currentPage}/${totalPages}`
            : `${total} deck${total === 1 ? '' : 's'}`;

        document.querySelectorAll('.ptable-pager').forEach(pager => {
            const status = pager.querySelector('[data-role="status"]');
            if (status) status.textContent = statusText;
            const prev = pager.querySelector('[data-page="prev"]');
            const next = pager.querySelector('[data-page="next"]');
            if (prev) prev.disabled = currentPage <= 1;
            if (next) next.disabled = currentPage >= totalPages;
            // Hide the pager entirely when there's only one page.
            pager.style.display = totalPages > 1 ? '' : 'none';
        });

        const note = document.getElementById('deck-count-note');
        if (note) {
            note.textContent = total > pageSize
                ? `Showing ${shown} of ${total} decks (page ${currentPage} of ${totalPages})`
                : `${total} deck${total === 1 ? '' : 's'}`;
        }
    }

    function updateSortIndicators() {
        document.querySelectorAll('th').forEach((th, idx) => {
            th.classList.remove('sorted-asc', 'sorted-desc');
            if (idx === currentSort.idx) {
                th.classList.add(currentSort.asc ? 'sorted-asc' : 'sorted-desc');
            }
        });
    }

    function populateTable(tableId, data) {
        const tbody = document.querySelector(`#${tableId} tbody`);
        const headers = document.querySelectorAll(`#${tableId} thead th`);
        tbody.innerHTML = '';
        let Deck = "dummy";

        // Only render the first `pageSize` rows; `data` is the FULL
        // filtered+sorted list so sorting/filtering already covered everything.
        data.slice(0, pageSize).forEach(item => {
            const row = document.createElement('tr');
            row.innerHTML = Array.from(headers).map(header => {
                const key = header.getAttribute('data-key');
                if (key === 'deck_name') {
                    Deck = item[key];
                    let URL = encodeURIComponent(Deck);
                    // Add tags below the deck name if they exist
                    const tags = item.tags || [];
                    let tagsHtml = '';
                    if (tags.length > 0) {
                        const visibleTags = tags.slice(0, 2);
                        const hiddenTags = tags.slice(2);

                        const visibleBadges = visibleTags.map(tag =>
                            `<span class="deck-tag">${escapeHtml(tag)}</span>`
                        ).join('');

                        let expanderHtml = '';
                        if (hiddenTags.length > 0) {
                            const hiddenBadges = hiddenTags.map(tag =>
                                `<span class="deck-tag">${escapeHtml(tag)}</span>`
                            ).join('');
                            expanderHtml = `<span class="deck-tag-wrapper"><span class="deck-tag deck-tag-expander">...</span><div class="deck-tags-hidden">${hiddenBadges}</div></span>`;
                        }

                        tagsHtml = `<div class="deck-tags">${visibleBadges}${expanderHtml}</div>`;
                    }
                    return `<td><a href="/decks/show/${URL}">${escapeHtml(item[key])}</a>${tagsHtml}</td>`;
                }
                if (key === 'commander') {
                    return `<td><a href="dummy">${escapeHtml(item[key])}</a></td>`;
                }
                if (key === 'player_name') {
                    return `<td><a id="${escapeHtml(item[key])}-link" href="/player/${encodeURIComponent(item[key])}">${escapeHtml(item[key])}</a></td>`;
                }
                if (key === 'color_identity') {
                    const imgs = Array.isArray(item.color_imgs) ? item.color_imgs : [];
                    const icons = imgs.map(src => `<img src="${escapeHtml(src)}" class="color-icon" alt="">`).join('');
                    return `<td><span class="color-pips">${icons}</span></td>`;
                }
                if (key === 'avg_win_turns') {
                    const avg = item.avg_win_turns;
                    const count = item.win_turns_count;
                    if (!count) return `<td>-</td>`;
                    return `<td>${escapeHtml(String(avg))} <small style="color:#aaa">(${escapeHtml(String(count))})</small></td>`;
                }
                const val = item[key];
                if (key === 'elo') {
                    if (val == null || val === 0) return `<td>-</td>`;
                    // Round the Elo to two decimal places.
                    const rounded = Math.round(Number(val) * 100) / 100;
                    return `<td>${escapeHtml(String(rounded))}</td>`;
                }
                if ((key === 'winrate_pct' || key === 'avg_win_turns') && val == null) return `<td>-</td>`;
                return `<td>${val != null && val !== '' ? escapeHtml(String(val)) : '0'}</td>`;
            }).join('');
            tbody.appendChild(row);

            // Set decklist link on the commander anchor
            const commanderLink = row.querySelector('a[href="dummy"]');
            if (commanderLink) {
                let url = item.decklist;
                if (url != null) {
                    commanderLink.href = url;
                } else {
                    commanderLink.removeAttribute("href");
                }
            }
        });
    }

    document.querySelectorAll('th').forEach((th, idx) => {
        th.addEventListener('click', function (event) {
            if (event.target.closest('#spieler-filter-btn') || document.getElementById('spieler-filter-dropdown').contains(event.target)) {
                return;
            }

            const dataType = th.getAttribute('data-type');

            if (currentSort.idx === idx) {
                currentSort.asc = !currentSort.asc;
            } else {
                currentSort = {
                    idx,
                    asc: true,
                    type: dataType
                };
            }

            currentPage = 1;   // re-sorting returns to the first page
            renderFilteredAndSortedTable();
        });
    });
});
