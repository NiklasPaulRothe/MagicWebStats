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
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 2,
            plugins: {
                legend: { display: false },
                title: { 
                    display: true, 
                    text: 'Likelihood of Appearance (%)',
                    color: '#f4c430',
                    font: { size: 16, weight: 'bold' }
                },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    color: '#f4c430',
                    font: { weight: 'bold', size: 11 },
                    formatter: value => value.toFixed(1)
                }
            },
            scales: {
                y: { 
                    beginAtZero: true, 
                    max: 100,
                    ticks: { color: 'antiquewhite' },
                    grid: { color: 'rgba(244, 196, 48, 0.1)' }
                },
                x: {
                    ticks: { color: 'antiquewhite' },
                    grid: { display: false }
                }
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
                fill: false,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 2,
            plugins: {
                legend: { display: false },
                title: { 
                    display: true, 
                    text: 'Average Decks per Table',
                    color: '#f4c430',
                    font: { size: 16, weight: 'bold' }
                },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    color: '#f4c430',
                    font: { weight: 'bold', size: 11 },
                    formatter: value => value.toFixed(2)
                }
            },
            scales: {
                y: { 
                    beginAtZero: true, 
                    max: 4,
                    ticks: { color: 'antiquewhite' },
                    grid: { color: 'rgba(244, 196, 48, 0.1)' }
                },
                x: {
                    ticks: { color: 'antiquewhite' },
                    grid: { display: false }
                }
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
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 2,
            plugins: {
                legend: { display: false },
                title: { 
                    display: true, 
                    text: 'Decks Using Color (%)',
                    color: '#f4c430',
                    font: { size: 16, weight: 'bold' }
                },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    color: '#f4c430',
                    font: { weight: 'bold', size: 11 },
                    formatter: value => value.toFixed(1)
                }
            },
            scales: {
                y: { 
                    beginAtZero: true, 
                    max: 100,
                    ticks: { color: 'antiquewhite' },
                    grid: { color: 'rgba(244, 196, 48, 0.1)' }
                },
                x: {
                    ticks: { color: 'antiquewhite' },
                    grid: { display: false }
                }
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
                tension: 0.3,
                pointRadius: 4,
                pointHoverRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 2,
            plugins: {
                legend: { display: false },
                title: { 
                    display: true, 
                    text: 'Games by Turn Count',
                    color: '#f4c430',
                    font: { size: 14, weight: 'bold' },
                    padding: {
                        top: 5,
                        bottom: 20
                    }
                },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    color: '#f4c430',
                    font: { weight: 'bold', size: 10 },
                    formatter: value => value
                }
            },
            scales: {
                x: { 
                    title: { 
                        display: true, 
                        text: 'Turn Count',
                        color: '#f4c430',
                        font: { size: 12 }
                    },
                    ticks: { color: 'antiquewhite', font: { size: 10 } },
                    grid: { color: 'rgba(244, 196, 48, 0.1)' }
                },
                y: {
                    beginAtZero: true,
                    title: { 
                        display: true, 
                        text: 'Number of Games',
                        color: '#f4c430',
                        font: { size: 12 }
                    },
                    ticks: { color: 'antiquewhite', font: { size: 10 } },
                    grid: { color: 'rgba(244, 196, 48, 0.1)' }
                }
            },
            layout: {
                padding: {
                    top: 10
                }
            }
        }
    });

    // === First Ko Line Chart ===
    const rawKoTurnData = document.getElementById('ko-turn-data').textContent;
    const koturnData = JSON.parse(rawKoTurnData);

    new Chart(document.getElementById('koturnsChart'), {
        type: 'line',
        data: {
            labels: koturnData.map(d => d.turn),
            datasets: [{
                label: 'Turn of First Ko',
                data: koturnData.map(d => d.count),
                backgroundColor: '#f4c430',
                borderColor: '#f4c430',
                fill: false,
                tension: 0.3,
                pointRadius: 4,
                pointHoverRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 2,
            plugins: {
                legend: { display: false },
                title: { 
                    display: true, 
                    text: 'Turn of First KO',
                    color: '#f4c430',
                    font: { size: 14, weight: 'bold' },
                    padding: {
                        top: 5,
                        bottom: 20
                    }
                },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    color: '#f4c430',
                    font: { weight: 'bold', size: 10 },
                    formatter: value => value
                }
            },
            scales: {
                x: { 
                    title: { 
                        display: true, 
                        text: 'KO Turn Count',
                        color: '#f4c430',
                        font: { size: 12 }
                    },
                    ticks: { color: 'antiquewhite', font: { size: 10 } },
                    grid: { color: 'rgba(244, 196, 48, 0.1)' }
                },
                y: {
                    beginAtZero: true,
                    title: { 
                        display: true, 
                        text: 'Number of Games',
                        color: '#f4c430',
                        font: { size: 12 }
                    },
                    ticks: { color: 'antiquewhite', font: { size: 10 } },
                    grid: { color: 'rgba(244, 196, 48, 0.1)' }
                }
            },
            layout: {
                padding: {
                    top: 10
                }
            }
        }
    });

    // === Shared color palette for consistent player colors ===
    // High contrast colors that are easily distinguishable
    const playerColorPalette = [
        '#f4c430',  // bright golden yellow
        '#ff6b6b',  // bright red
        '#4ecdc4',  // bright teal
        '#95e1d3',  // mint green
        '#ff9f43',  // bright orange
        '#a29bfe',  // light purple
        '#fd79a8',  // pink
        '#00b894',  // emerald green
        '#fdcb6e',  // light yellow
        '#6c5ce7',  // purple
        '#e17055',  // coral
        '#74b9ff',  // sky blue
        '#55efc4',  // aqua
        '#ffeaa7',  // pale yellow
        '#fab1a0'   // peach
    ];

    // Function to assign consistent colors based on player names
    function getPlayerColors(labels) {
        const colorMap = {};
        const sortedLabels = [...labels].sort(); // Sort to ensure consistency
        sortedLabels.forEach((label, index) => {
            colorMap[label] = playerColorPalette[index % playerColorPalette.length];
        });
        return labels.map(label => colorMap[label]);
    }

    // === Final Blow Chart ===
    const finalBlowData = JSON.parse(document.getElementById('final-blow-data').textContent);
    const fbLabels = Object.keys(finalBlowData);
    const fbCounts = Object.values(finalBlowData);
    const fbTotal = fbCounts.reduce((a, b) => a + b, 0);

    new Chart(document.getElementById('finalBlowChart'), {
        type: 'pie',
        data: {
            labels: fbLabels,
            datasets: [{
                data: fbCounts,
                backgroundColor: getPlayerColors(fbLabels),
                borderColor: '#1e1e1e',
                borderWidth: 2,
                hoverOffset: 10,
                hoverBorderColor: '#f4c430',
                hoverBorderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: true,
                    position: 'right',
                    align: 'center',
                    maxWidth: 200,
                    labels: {
                        color: 'antiquewhite',
                        font: { 
                            size: 12,
                            weight: '600',
                            family: "'Segoe UI', sans-serif"
                        },
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 10,
                        boxWidth: 10,
                        boxHeight: 10,
                        generateLabels: function(chart) {
                            const data = chart.data;
                            const total = data.datasets[0].data.reduce((a, b) => a + b, 0);
                            return data.labels.map((label, i) => {
                                const value = data.datasets[0].data[i];
                                const percentage = ((value / total) * 100).toFixed(1);
                                return {
                                    text: `${label}: ${value} (${percentage}%)`,
                                    fillStyle: data.datasets[0].backgroundColor[i],
                                    fontColor: 'antiquewhite',
                                    hidden: false,
                                    index: i
                                };
                            });
                        }
                    }
                },
                title: {
                    display: true,
                    text: 'Final Blow Distribution',
                    color: '#f4c430',
                    font: { 
                        weight: 'bold', 
                        size: 16,
                        family: "'Segoe UI', sans-serif"
                    },
                    padding: {
                        top: 5,
                        bottom: 10
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(30, 30, 30, 0.95)',
                    titleColor: '#f4c430',
                    bodyColor: 'antiquewhite',
                    borderColor: '#f4c430',
                    borderWidth: 1,
                    padding: 10,
                    displayColors: true,
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((value / total) * 100).toFixed(1);
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                },
                datalabels: {
                    display: false
                }
            },
            layout: {
                padding: {
                    top: 5,
                    bottom: 5,
                    left: 5,
                    right: 20
                }
            }
        }
    });

    // === First KO Chart ===
    const firstKoData = JSON.parse(document.getElementById('first-ko-data').textContent);
    const fkLabels = Object.keys(firstKoData);
    const fkCounts = Object.values(firstKoData);
    const fkTotal = fkCounts.reduce((a, b) => a + b, 0);

    new Chart(document.getElementById('firstKoChart'), {
        type: 'pie',
        data: {
            labels: fkLabels,
            datasets: [{
                data: fkCounts,
                backgroundColor: getPlayerColors(fkLabels),
                borderColor: '#1e1e1e',
                borderWidth: 2,
                hoverOffset: 10,
                hoverBorderColor: '#f4c430',
                hoverBorderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: true,
                    position: 'right',
                    align: 'center',
                    maxWidth: 200,
                    labels: {
                        color: 'antiquewhite',
                        font: { 
                            size: 12,
                            weight: '600',
                            family: "'Segoe UI', sans-serif"
                        },
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 10,
                        boxWidth: 10,
                        boxHeight: 10,
                        generateLabels: function(chart) {
                            const data = chart.data;
                            const total = data.datasets[0].data.reduce((a, b) => a + b, 0);
                            return data.labels.map((label, i) => {
                                const value = data.datasets[0].data[i];
                                const percentage = ((value / total) * 100).toFixed(1);
                                return {
                                    text: `${label}: ${value} (${percentage}%)`,
                                    fillStyle: data.datasets[0].backgroundColor[i],
                                    fontColor: 'antiquewhite',
                                    hidden: false,
                                    index: i
                                };
                            });
                        }
                    }
                },
                title: {
                    display: true,
                    text: 'First KO Distribution',
                    color: '#f4c430',
                    font: { 
                        weight: 'bold', 
                        size: 16,
                        family: "'Segoe UI', sans-serif"
                    },
                    padding: {
                        top: 5,
                        bottom: 10
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(30, 30, 30, 0.95)',
                    titleColor: '#f4c430',
                    bodyColor: 'antiquewhite',
                    borderColor: '#f4c430',
                    borderWidth: 1,
                    padding: 10,
                    displayColors: true,
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((value / total) * 100).toFixed(1);
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                },
                datalabels: {
                    display: false
                }
            },
            layout: {
                padding: {
                    top: 5,
                    bottom: 5,
                    left: 5,
                    right: 20
                }
            }
        }
    });

});
