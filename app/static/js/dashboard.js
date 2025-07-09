  document.addEventListener('DOMContentLoaded', function () {
    const rawData = document.getElementById('color-usage-data').textContent;
    const colorUsage = JSON.parse(rawData);
    const labels = colorUsage.map(c => c.color);

    Chart.register(ChartDataLabels);

    // === Likelihood Chart ===
    new Chart(document.getElementById('likelihoodChart'), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Likelihood (%)',
                data: colorUsage.map(c => c.likelihood),
                backgroundColor: '#f4c430'
            }]
        },
        options: {
            responsive: false,
            plugins: {
                legend: { display: false },
                title: { display: true, text: 'Likelihood of Appearance (%)' },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    color: '#fff',
                    font: { weight: 'bold' },
                    formatter: value => value.toFixed(1)
                }
            },
            scales: {
                y: { beginAtZero: true, max: 100 }
            }
        }
    });

    // === Average Chart ===
    new Chart(document.getElementById('averageChart'), {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Average per Table',
                data: colorUsage.map(c => c.average),
                backgroundColor: '#f4c430',
                borderColor: '#f4c430',
                fill: false
            }]
        },
        options: {
            responsive: false,
            plugins: {
                legend: { display: false },
                title: { display: true, text: 'Average Decks per Table' },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    color: '#fff',
                    font: { weight: 'bold' },
                    formatter: value => value.toFixed(2)
                }
            },
            scales: {
                y: { beginAtZero: true, max: 4 }
            }
        }
    });

    // === Deck Percentage Chart ===
    new Chart(document.getElementById('deckPercentageChart'), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Deck Usage (%)',
                data: colorUsage.map(c => c.deck_percentage),
                backgroundColor: '#f4c430'
            }]
        },
        options: {
            responsive: false,
            plugins: {
                legend: { display: false },
                title: { display: true, text: 'Decks Using Color (%)' },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    color: '#fff',
                    font: { weight: 'bold' },
                    formatter: value => value.toFixed(1)
                }
            },
            scales: {
                y: { beginAtZero: true, max: 100 }
            }
        }
    });

        // === Turns Line Chart ===
    const rawTurnData = document.getElementById('turn-data').textContent;
    const turnData = JSON.parse(rawTurnData);

    new Chart(document.getElementById('turnsChart'), {
        type: 'line',
        data: {
            labels: turnData.map(d => d.turn),
            datasets: [{
                label: 'Games per Turn Count',
                data: turnData.map(d => d.count),
                backgroundColor: '#f4c430',
                borderColor: '#f4c430',
                fill: false,
                tension: 0.1
            }]
        },
        options: {
            responsive: false,
            plugins: {
                legend: { display: false },
                title: { display: true, text: 'Games by Turn Count' },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    color: '#fff',
                    font: { weight: 'bold' },
                    formatter: value => value
                }
            },
            scales: {
                x: { title: { display: true, text: 'Turn Count' } },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: 'Number of Games' }
                }
            }
        }
    });

});
