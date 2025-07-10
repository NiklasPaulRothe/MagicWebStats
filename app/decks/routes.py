import statistics

from flask import render_template, flash, redirect, url_for, request, session, current_app
from flask_login import login_required, current_user
from sqlalchemy import select, and_, desc, func

from app import db, models, third_party_data
from app.auth import role_required
from app.decks import bp
from app.decks.forms import DeckEditForm
from app.models import Deck, Player, User, Game, Participant
from app.third_party_data.deckbuilder import load_cards_from_archidekt


@bp.route('/edit/<deckname>', methods=['GET', 'POST'])
@login_required
def deck_edit(deckname):
    deck = Deck.query.filter(Deck.Name == deckname).one()
    user = User.query.filter(User.username == current_user.username).one()
    owner = Player.query.filter(user.spieler == Player.id).one()
    if deck.Player != owner.id:
        flash('Du bist nicht berechtigt dieses Deck zu bearbeiten')
        return redirect(url_for('main.index'))

    form = DeckEditForm()

    deckname = deckname + " (" + deck.Commander + ")"

    if not form.validate_on_submit():
        print(form.errors)

    if form.validate_on_submit():
        deck.Name = form.name.data
        deck.Active = not form.archive.data
        db.session.commit()
        if (form.decklist.data != ""):
            deck.decklist = form.decklist.data
            deckbuilder = third_party_data.deckbuilder.get_id_from_url(form.decklist.data)
            deck.decksite = deckbuilder[0].strip()
            deck.archidekt_id = deckbuilder[1].strip()
            db.session.commit()
            try:
                load_cards_from_archidekt(deck.archidekt_id, deck.id)
                db.session.commit()
            except:
                flash('Karten für dieses Deck konnten nicht korrekt geladen werden.')
                db.session.rollback()
        return redirect(url_for('main.user', username=current_user.username))
    form.name.default = deck.Name
    form.decklist.default = deck.decklist
    form.current_name.default = deck.Name
    form.process()

    return render_template('decks/edit.html', form=form, deckname=deckname)

@bp.route('/choose_image/<deckname>', methods=['GET'], strict_slashes=False)
@login_required
def choose_commander_image(deckname):
    deck = models.Deck.query.filter_by(Name=deckname).first()
    if not deck:
        flash("Deck not found", "error")
        return redirect(url_for('main.index'))

    # Get all cards that match the commander's name (could be different versions)
    cards = models.Card.query.filter_by(Name=deck.Commander).all()

    images = [card.image_uri for card in cards if card.image_uri]

    return render_template('decks/choose_image.html', deckname=deckname, commander=deck.Commander, images=images)

@bp.route('/set_commander_image/<deckname>', methods=['POST'])
@login_required
def set_commander_image(deckname):
    image_uri = request.form.get('image_uri')
    deck = models.Deck.query.filter_by(Name=deckname).first()

    if not deck or not image_uri:
        flash("Fehler beim Aktualisieren des Bildes", "error")
        return redirect(url_for('decks.deck_show', deckname=deckname))
    deck.image_uri = image_uri
    db.session.commit()

    flash("Commander-Bild aktualisiert!", "success")
    return redirect(url_for('decks.deck_show', deckname=deckname))


from collections import defaultdict

@bp.route('/show/<deckname>', methods=['GET'], strict_slashes=False)
@login_required
def deck_show(deckname):
    current_app.logger.info(deckname)

    deck = models.Deck.query.filter_by(Name=deckname).first_or_404()
    user = models.User.query.filter_by(username=current_user.username).one()
    is_owner = (deck.Player == user.id)

    # 1. Get all game participations for this deck
    participants = models.Participant.query.filter_by(
        player_id=deck.Player,
        deck_id=deck.id
    ).order_by(models.Participant.game_id.desc()).all()

    game_ids = [p.game_id for p in participants]
    if not game_ids:
        games = {}
        participants_by_game = {}
        players = {}
        decks = {}
    else:
        # 2. Get all games
        games = {g.id: g for g in models.Game.query.filter(models.Game.id.in_(game_ids)).all()}

        # 3. Get all participants for these games
        all_participants = models.Participant.query.filter(
            models.Participant.game_id.in_(game_ids)
        ).all()

        # 4. Collect players and decks used
        player_ids = {p.player_id for p in all_participants}
        deck_ids = {p.deck_id for p in all_participants}

        players = {p.id: p for p in models.Player.query.filter(models.Player.id.in_(player_ids)).all()}
        decks = {d.id: d for d in models.Deck.query.filter(models.Deck.id.in_(deck_ids)).all()}

        # 5. Group participants by game
        participants_by_game = defaultdict(list)
        for p in all_participants:
            participants_by_game[p.game_id].append(p)

    # === Collect data rows and win turn stats ===
    row = []
    win_turns = []

    for game_id in game_ids:
        game_data = games[game_id]
        if game_data.Winner == deck.Player and game_data.turns:
            win_turns.append(game_data.turns)

        opponents = [
            p for p in participants_by_game.get(game_id, [])
            if p.player_id != deck.Player
        ]

        opponent_data = []
        for opp in opponents:
            player = players.get(opp.player_id)
            deck_obj = decks.get(opp.deck_id)
            opponent_data.append({
                "player_name": player.Name if player else "Unknown",
                "deck_name": deck_obj.Name if deck_obj else "Unknown Deck",
                "commander_image": deck_obj.image_uri if deck_obj and deck_obj.image_uri else "/static/img/default_commander.png"
            })

        winner_name = players.get(game_data.Winner).Name if players.get(game_data.Winner) else "Unbekannt"

        row.append({
            "Datum": game_data.Date.strftime("%Y-%m-%d"),
            "Gegner": opponent_data,
            "Winner": winner_name,
        })

    # === Basic deck stats ===
    total_games = len(game_ids)
    wins = sum(1 for g in game_ids if games[g].Winner == deck.Player)
    winrate = round((wins / total_games) * 100, 1) if total_games else 0
    last_played = games[game_ids[0]].Date.strftime("%Y-%m-%d") if game_ids else "Nie"

    # === Turn stats for wins ===
    deck_stats = {
        "games": total_games,
        "wins": wins,
        "winrate": winrate,
        "last_played": last_played,
        "avg_turns": round(statistics.mean(win_turns), 1) if win_turns else "–",
        "median_turns": statistics.median(win_turns) if win_turns else "–",
        "min_turns": min(win_turns) if win_turns else "–",
        "max_turns": max(win_turns) if win_turns else "–"
    }

    return render_template(
        'decks/show.html',
        deckname=deck.Name,
        commander=deck.image_uri or "/static/img/default_commander.png",
        games=row,
        deck_stats=deck_stats,
        is_owner=is_owner
    )



@bp.route('/elo', methods=['GET'])
@role_required('admin')
@login_required
def calculate_elo():
    decks = Deck.query.all()
    elo_ratings = {deck.id: {'elo_rating': 1200, 'games_played': 0} for deck in decks}

    games = Game.query.all()
    for game in games:
        participants = Participant.query.filter_by(game_id=game.id).all()
        if len(participants) < 3:
            continue

        #if game.id > 158:
         #   continue

        deck_ratings = {p.deck_id: elo_ratings[p.deck_id]['elo_rating'] for p in participants if p.deck_id in elo_ratings}

        for participant in participants:
            deck = Deck.query.get(participant.deck_id)
            if deck.Player != participant.player_id:
                continue

            rating = elo_ratings[participant.deck_id]['elo_rating']

            expected_scores = {deck_id: expected_score(rating, opponent_rating) for deck_id, opponent_rating in deck_ratings.items() if deck_id != participant.deck_id}
            lowest_expected_score = min(expected_scores.values())
            threshold = (1 - lowest_expected_score) * 0.6 + lowest_expected_score
            filtered_expected_scores = [score for score in expected_scores.values() if score <= threshold]

            actual_score = 1 if game.Winner == participant.player_id else 0
            games_played = elo_ratings[participant.deck_id]['games_played']
            expected_score_avg = sum(filtered_expected_scores) / len(filtered_expected_scores)
            adjusted_rating = update_elo_rating(rating, actual_score, expected_score_avg, games_played)

            elo_ratings[participant.deck_id]['elo_rating'] = adjusted_rating
            elo_ratings[participant.deck_id]['games_played'] += 1

    # Update Elo ratings in the database
    for deck_id, values in elo_ratings.items():
        deck = Deck.query.get(deck_id)
        deck.elo_rating = values['elo_rating']
        db.session.add(deck)

    db.session.commit()
    return redirect(url_for('main.index'), code=302)

def expected_score(rating, opponent_rating):
    return 1 / (1 + 10 ** ((opponent_rating - rating) / 180))

def update_elo_rating(current_rating, actual_score, expected_score, games_played):
    match games_played:
        case games_played if games_played > 50:
            adjustment_factor = 30
        case games_played if games_played <= 50 & games_played > 30:
            adjustment_factor = 75
        case _:
            adjustment_factor = 150
    value =  adjustment_factor * (actual_score - expected_score)
    if value > 0:
        return current_rating + value
    else:
        return current_rating + value/3
