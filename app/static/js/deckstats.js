let originalData = [];
let currentSort = { idx: null, asc: true, type: null };

document.addEventListener('DOMContentLoaded', function () {
    fetch('/api/deck-data')
        .then(response => response.json())
        .then(data => {
            originalData = data;
            populateSpielerFilter('spieler-filter-dropdown', data);
            renderFilteredAndSortedTable();
        });

    document.getElementById('apply-min-spiele-filter').addEventListener('click', renderFilteredAndSortedTable);

    document.getElementById('reset-filters').addEventListener('click', () => {
        document.getElementById('min-spiele-filter').value = '';
        document.querySelectorAll('#spieler-filter-dropdown input[type="checkbox"]').forEach(cb => cb.checked = true);
        currentSort = { idx: null, asc: true, type: null };
        renderFilteredAndSortedTable();
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
        const uniquePlayers = [];

        data.forEach(item => {
            const playerName = item.Spieler[0];
            if (!uniquePlayers.includes(playerName)) {
                uniquePlayers.push(playerName);
                const label = document.createElement('label');
                label.innerHTML = `<input type="checkbox" value="${playerName}" checked> ${playerName}`;
                dropdown.appendChild(label);
                dropdown.appendChild(document.createElement('br'));
            }
        });

        dropdown.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('click', function (e) {
                e.stopPropagation(); // ✅ prevent sort on dropdown interaction
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
            return item['Spiele'] >= minValue && checkedPlayers.includes(item.Spieler[0]);
        });

        if (currentSort.idx !== null) {
            const headers = document.querySelectorAll('th');
            const key = headers[currentSort.idx].getAttribute('data-key');
            filtered.sort((a, b) => {
                const valA = a[key] || '';
                const valB = b[key] || '';
                if (currentSort.type === 'number') {
                    return currentSort.asc ? valA - valB : valB - valA;
                } else {
                    return currentSort.asc
                        ? valA.toString().localeCompare(valB)
                        : valB.toString().localeCompare(valA);
                }
            });
        }

        updateSortIndicators();
        populateTable('deck-stats-table', filtered);
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

        data.forEach(item => {
            const row = document.createElement('tr');
            row.innerHTML = Array.from(headers).map(header => {
                const key = header.getAttribute('data-key');
                if (key === 'Deckname') {
                    Deck = item[key];
                    let URL = encodeURIComponent(Deck);
                    return `<td><a id="${Deck}-show" href="/decks/show/${URL}">${item[key] || ''}</a></td>`;
                }
                if (key === 'Commander') {
                    return `<td><a id="${Deck}-list" href="dummy">${item[key] || ''}</a></td>`;
                }
                return `<td>${item[key] || ''}</td>`;
            }).join('');
            tbody.appendChild(row);

            const decklist = document.getElementById(`${Deck}-list`);
            let url = item["Decklist"];
            if (url && url[0] != null) {
                decklist.href = url;
            } else {
                decklist.removeAttribute("href");
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

            renderFilteredAndSortedTable();
        });
    });
});
