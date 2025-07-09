function add_player_list(player_id, players) {
    const dropdown = document.getElementById("players-" + player_id + "-player");
    const borrowed = document.getElementById("players-" + player_id + "-lender");
    dropdown.innerHTML = "";
    borrowed.innerHTML = "";
    players.forEach(player => {
        const option1 = new Option(player, player);
        const option2 = new Option(player, player);
        dropdown.add(option1);
        borrowed.add(option2);
    });
}

function add_deck_list(player_id, decks) {
    const dropdown = document.getElementById("players-" + player_id + "-deck");
    dropdown.innerHTML = "";
    const isBorrowed = document.getElementById("players-" + player_id + "-borrowed").checked;
    const selectedName = isBorrowed
        ? document.getElementById("players-" + player_id + "-lender").value
        : document.getElementById("players-" + player_id + "-player").value;

    decks.forEach(deck => {
        if (deck[2] === selectedName) {
            const option = new Option(`${deck[0]} (${deck[1]})`, `${deck[0]} (${deck[1]})`);
            dropdown.add(option);
        }
    });
}

document.addEventListener('DOMContentLoaded', function () {
    const playersContainer = document.getElementById('players-fields');
    const addPlayerButton = document.getElementById('add-player');
    const maxPlayers = parseInt(document.getElementById('max-players').value);
    const minPlayers = parseInt(document.getElementById('min-players').value);
    const players = JSON.parse(document.getElementById('player-data').textContent);
    const decks = JSON.parse(document.getElementById('deck-data').textContent);
    let currentPlayers = parseInt(document.getElementById('initial-player-count').value);

    function setupPlayerListeners(playerIndex) {
        add_player_list(playerIndex, players);
        add_deck_list(playerIndex, decks);

        document.getElementById(`players-${playerIndex}-player`).addEventListener("change", () => {
            add_deck_list(playerIndex, decks);
        });

        document.getElementById(`players-${playerIndex}-lender`).addEventListener("change", () => {
            if (document.getElementById(`players-${playerIndex}-borrowed`).checked) {
                add_deck_list(playerIndex, decks);
            }
        });

        document.getElementById(`players-${playerIndex}-borrowed`).addEventListener("change", () => {
            add_deck_list(playerIndex, decks);
        });
    }

    for (let i = 0; i < currentPlayers; i++) {
        setupPlayerListeners(i);
    }

    addPlayerButton.addEventListener('click', function () {
        if (currentPlayers < maxPlayers) {
            const playerIndex = currentPlayers;
            currentPlayers++;

            const playerWrapper = document.createElement('div');
            playerWrapper.classList.add('field-list-item', 'player-fields');
            playerWrapper.innerHTML = `
                <div>
                    <label for="players-${playerIndex}-player">Player</label>
                    <select name="players-${playerIndex}-player" id="players-${playerIndex}-player"></select>
                </div>
                <div>
                    <label for="players-${playerIndex}-deck">Deck</label>
                    <select name="players-${playerIndex}-deck" id="players-${playerIndex}-deck"></select>
                </div>
                <div>
                    <label for="players-${playerIndex}-borrowed">Borrowed</label>
                    <input type="checkbox" name="players-${playerIndex}-borrowed" id="players-${playerIndex}-borrowed">
                </div>
                <div>
                    <label for="players-${playerIndex}-lender">Geliehen von</label>
                    <select name="players-${playerIndex}-lender" id="players-${playerIndex}-lender"></select>
                </div>
                <div>
                    <label for="players-${playerIndex}-early_fast_mana">Early Fast Mana</label>
                    <input type="checkbox" name="players-${playerIndex}-early_fast_mana" id="players-${playerIndex}-early_fast_mana">
                </div>
                <div style="grid-column: 1 / -1;">
                    <button type="button" class="remove-player">Remove</button>
                </div>
            `;
            playersContainer.appendChild(playerWrapper);
            setupPlayerListeners(playerIndex);

            playerWrapper.querySelector('.remove-player').addEventListener('click', function () {
                if (currentPlayers > minPlayers) {
                    playerWrapper.remove();
                    currentPlayers--;
                }
            });
        }
    });

    document.querySelectorAll('.remove-player').forEach(button => {
        button.addEventListener('click', function () {
            if (currentPlayers > minPlayers) {
                button.parentElement.parentElement.remove();
                currentPlayers--;
            }
        });
    });
});
