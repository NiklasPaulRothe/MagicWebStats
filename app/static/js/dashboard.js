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
    const finalBlowData = JSON.parse(document.getElementById('final-blow-data').textContent);

const fbLabels = Object.keys(finalBlowData);
const fbCounts = Object.values(finalBlowData);

new Chart(document.getElementById('finalBlowChart'), {
    type: 'pie',
    data: {
        labels: fbLabels,
        datasets: [{
            data: fbCounts,
            backgroundColor: [
                '#f4c430',  // golden yellow
                '#e6194b',  // strong red
                '#3cb44b',  // green
                '#4363d8',  // royal blue
                '#f58231',  // orange
                '#911eb4',  // purple
                '#46f0f0',  // cyan
                '#a9a9a9',  // gray
                '#ffe119',  // bright yellow
                '#000075'   // deep navy
            ],
            borderColor: '#222',
            borderWidth: 2,
            hoverOffset: 10
        }]
    },
    options: {
        responsive: false,
        layout: {
            padding: 10
        },
        plugins: {
            legend: {
                position: 'bottom',
                labels: {
                    color: 'antiquewhite',
                    usePointStyle: true,
                    padding: 20,
                    boxWidth: 12
                }
            },
            title: {
                display: true,
                text: 'Final Blow Distribution',
                color: '#f4c430',
                font: { weight: 'bold', size: 16 }
            },
            tooltip: {
                bodyColor: 'black',
                titleColor: 'black',
                backgroundColor: '#f4f4f4'
            },
            datalabels: {
                color: 'black', 
                font: {
                    weight: 'bold',
                    size: 12
                },
                formatter: (value, ctx) => value
            }
        },
        layout: {
            padding: { top: 10, bottom: 10 }
        }
    }
});

});
