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
        return redirect(url_for('main.user', spieler=current_user.username))
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

from collections import defaultdict, Counter
import statistics

@bp.route('/show/<deckname>', methods=['GET'], strict_slashes=False)
@login_required
def deck_show(deckname):
    current_app.logger.info(deckname)

    deck = models.Deck.query.filter_by(Name=deckname).first_or_404()
    user = models.User.query.filter_by(username=current_user.username).one()
    is_owner = (deck.Player == user.spieler)

    participants = models.Participant.query.filter_by(
        player_id=deck.Player,
        deck_id=deck.id
    ).order_by(models.Participant.game_id.desc()).all()

    game_ids = [p.game_id for p in participants]
    games = {}
    participants_by_game = defaultdict(list)
    players, decks = {}, {}

    if game_ids:
        games = {g.id: g for g in models.Game.query.filter(models.Game.id.in_(game_ids)).all()}
        all_participants = models.Participant.query.filter(
            models.Participant.game_id.in_(game_ids)
        ).all()

        player_ids = {p.player_id for p in all_participants}
        deck_ids = {p.deck_id for p in all_participants}

        players = {p.id: p for p in models.Player.query.filter(models.Player.id.in_(player_ids)).all()}
        decks = {d.id: d for d in models.Deck.query.filter(models.Deck.id.in_(deck_ids)).all()}

        for p in all_participants:
            participants_by_game[p.game_id].append(p)

    row = []
    win_turns = []
    games_by_size = {3: [], 4: [], 5: []}
    win_turns_by_size = {3: [], 4: [], 5: []}
    wins_by_size = {3: 0, 4: 0, 5: 0}
    total_by_size = {3: 0, 4: 0, 5: 0}

    for game_id in game_ids:
        game_data = games[game_id]
        all_participants_in_game = participants_by_game.get(game_id, [])
        num_players = len(all_participants_in_game)

        opponents = [p for p in all_participants_in_game if p.player_id != deck.Player]
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
        turn_count = game_data.turns if game_data.turns else "-"
        final_blow = game_data.final_blow if game_data.final_blow else "Not Tracked"


        row.append({
            "Datum": game_data.Date.strftime("%Y-%m-%d"),
            "Gegner": opponent_data,
            "Winner": winner_name,
            "Turns": turn_count,
            "Final_Blow": final_blow
        })

        # Collect full win turn stats
        if game_data.Winner == deck.Player and game_data.turns:
            win_turns.append(game_data.turns)

        # Stats by table size
        if num_players in (3, 4, 5):
            total_by_size[num_players] += 1
            if game_data.Winner == deck.Player:
                wins_by_size[num_players] += 1
                if game_data.turns:
                    win_turns_by_size[num_players].append(game_data.turns)

    # === General deck stats ===
    total_games = len(game_ids)
    wins = sum(1 for g in game_ids if games[g].Winner == deck.Player)
    winrate = round((wins / total_games) * 100, 1) if total_games else 0
    last_played = games[game_ids[0]].Date.strftime("%Y-%m-%d") if game_ids else "Nie"

    # === Average participant count ===
    participant_counts = [len(participants_by_game[gid]) for gid in game_ids if gid in participants_by_game]
    average_participants = round(statistics.mean(participant_counts), 1) if participant_counts else "–"

    # === Turn stats for wins ===
    deck_stats = {
        "games": total_games,
        "wins": wins,
        "winrate": winrate,
        "last_played": last_played,
        "avg_turns": round(statistics.mean(win_turns), 1) if win_turns else "–",
        "median_turns": statistics.median(win_turns) if win_turns else "–",
        "min_turns": min(win_turns) if win_turns else "–",
        "max_turns": max(win_turns) if win_turns else "–",
        "avg_participants": average_participants
    }

    deck_stats_by_size = {}
    for size in (3, 4, 5):
        games_count = total_by_size[size]
        wins_count = wins_by_size[size]
        turns = win_turns_by_size[size]

        deck_stats_by_size[size] = {
            "games": games_count,
            "wins": wins_count,
            "winrate": round((wins_count / games_count) * 100, 1) if games_count else "–",
            "avg_turns": round(statistics.mean(turns), 1) if turns else "–",
            "median_turns": statistics.median(turns) if turns else "–"
        }

    # Load achievements for this deck (non-functional checkboxes for now)
    achievements = models.Achievement.query.filter_by(deck=deck.id).all()

    # === Participant field averages (strictly for Player 1 and User ID 1) ===
    show_private_avgs = (deck.Player == 1 and getattr(current_user, "id", None) == 1)
    participant_avgs = {}
    if show_private_avgs and participants:
        fields = [
            "mulligans",
            "landdrops",
            "enough_mana",
            "enough_gas",
            "deckplan",
            "unanswered_threats",
            "fun_moments",
            "lands",
        ]
        percent_fields = {"enough_mana", "enough_gas", "deckplan", "unanswered_threats", "fun_moments"}
        for f in fields:
            numeric_values = []
            for p in participants:
                if not hasattr(p, f):
                    continue
                raw = getattr(p, f)
                if raw is None:
                    continue
                try:
                    num = float(raw)
                except Exception:
                    continue
                # Ignore -1 for 'lands'
                if (f == "lands" or f == "landdrops") and num == -1:
                    continue
                numeric_values.append(num)

            if not numeric_values:
                participant_avgs[f] = "–"
                continue

            if f in percent_fields:
                # Convert mean to percentage string
                participant_avgs[f] = f"{round(statistics.mean(numeric_values) * 100, 1)}%"
            else:
                # Keep as numeric average (e.g., mulligans, landdrops, lands)
                participant_avgs[f] = round(statistics.mean(numeric_values), 2)

        # === Private comments (Player 1 owner and User ID 1) ===
        show_private_comments = (deck.Player == 1 and getattr(current_user, "id", None) == 1)
        private_comments = []
        if show_private_comments and participants:
            # Try to fetch a last rework date if present on the deck model;
            last_rework_date = getattr(deck, "last_patch")
            # Build a quick game lookup if not already done
            # games dict already exists above keyed by id
            for p in participants:
                text = getattr(p, "comments", None)
                if not text:
                    continue
                game_obj = games.get(p.game_id)
                if not game_obj:
                    continue
                if game_obj.Date < last_rework_date:
                    continue
                private_comments.append({
                    "game_id": p.game_id,
                    "date": game_obj.Date.strftime("%Y-%m-%d") if getattr(game_obj, "Date", None) else "",
                    "text": text
                })
            # Sort newest first
            private_comments.sort(key=lambda x: x["date"], reverse=True)

    return render_template(
        'decks/show.html',
        deckname=deck.Name,
        commander=deck.image_uri or "/static/img/default_commander.png",
        games=row,
        deck_stats=deck_stats,
        deck_stats_by_size=deck_stats_by_size,
        is_owner=is_owner,
        achievements=achievements,
        show_private_avgs=show_private_avgs,
        participant_avgs=participant_avgs,
        show_private_comments=show_private_comments,
        private_comments=private_comments
    )


@bp.route('/achievements/<int:achievement_id>/set', methods=['POST'])
@login_required
def set_achievement_progress(achievement_id):
    from flask import request, jsonify

    ach = models.Achievement.query.get_or_404(achievement_id)

    # Read desired value from JSON
    payload = request.get_json(silent=True) or {}
    try:
        desired = int(payload.get('achieved', 0))
    except (TypeError, ValueError):
        desired = ach.achieved or 0

    # Clamp to [0, anzahl]
    max_allowed = ach.anzahl or 0
    desired = max(0, min(desired, max_allowed))

    # Only write if changed
    if (ach.achieved or 0) != desired:
        ach.achieved = desired
        db.session.commit()

    return jsonify({
        "ok": True,
        "achievement_id": ach.id,
        "achieved": ach.achieved or 0,
        "max": max_allowed
    })

@bp.route('/achievements/<int:achievement_id>/delete', methods=['POST'])
@login_required
def delete_achievement(achievement_id):
    from flask import jsonify

    ach = models.Achievement.query.get_or_404(achievement_id)

    # Only the deck owner may delete an achievement
    deck = models.Deck.query.get_or_404(ach.deck)
    user = models.User.query.filter_by(username=current_user.username).one()
    if deck.Player != user.spieler:
        return jsonify({"ok": False, "message": "Nicht berechtigt."}), 403

    db.session.delete(ach)
    db.session.commit()

    return jsonify({"ok": True, "deleted_id": achievement_id})


@bp.route('/achievements/add', methods=['POST'])
@login_required
def add_achievement():
    from flask import request, jsonify

    # Accept both JSON and form submissions to improve robustness
    if request.is_json:
        data = request.get_json(silent=True) or {}
        deckname = (data.get('deckname') or '').strip()
        titel = (data.get('titel') or '').strip()
        beschreibung = (data.get('beschreibung') or '').strip()
        anzahl = data.get('anzahl')
    else:
        form = request.form or {}
        deckname = (form.get('deckname') or '').strip()
        titel = (form.get('titel') or '').strip()
        beschreibung = (form.get('beschreibung') or '').strip()
        anzahl = form.get('anzahl')

    if not deckname or not titel:
        return jsonify({"ok": False, "message": "Deckname und Titel sind erforderlich."}), 400

    try:
        anzahl = int(anzahl)
    except (TypeError, ValueError):
        anzahl = 1
    if anzahl < 1:
        anzahl = 1

    deck = models.Deck.query.filter_by(Name=deckname).first_or_404()

    ach = models.Achievement(
        titel=titel,
        beschreibung=beschreibung,
        anzahl=anzahl,
        achieved=0,
        deck=deck.id
    )
    db.session.add(ach)
    db.session.commit()

    return jsonify({
        "ok": True,
        "achievement": {
            "id": ach.id,
            "titel": ach.titel,
            "beschreibung": ach.beschreibung,
            "anzahl": ach.anzahl,
            "achieved": ach.achieved
        }
    }), 201



@bp.route('/elo', methods=['GET'])
@role_required('admin')
@login_required
def calculate_elo():
    decks = Deck.query.all()
    elo_ratings = {deck.id: {'elo_rating': 1000, 'games_played': 0} for deck in decks}

    games = Game.query.all()
    for game in games:
        participants = Participant.query.filter_by(game_id=game.id).all()
        if len(participants) < 3 or len(participants) > 5:
            continue

        #if game.id > 158:
         #   continue

        player = len(participants)
        deck_ratings = {p.deck_id: elo_ratings[p.deck_id]['elo_rating'] for p in participants if p.deck_id in elo_ratings}

        for participant in participants:
            deck = Deck.query.get(participant.deck_id)
            if deck.Player != participant.player_id and deck.Player != 24:
                continue

            rating = elo_ratings[participant.deck_id]['elo_rating']

            expected_scores = {deck_id: expected_score(rating, opponent_rating) for deck_id, opponent_rating in deck_ratings.items() if deck_id != participant.deck_id}
            lowest_expected_score = min(expected_scores.values())
            threshold = (1 - lowest_expected_score) * 0.6 + lowest_expected_score
            filtered_expected_scores = [score for score in expected_scores.values() if score <= threshold]

            actual_score = 1 if game.Winner == participant.player_id else 0
            games_played = elo_ratings[participant.deck_id]['games_played']
            expected_score_avg = sum(filtered_expected_scores) / len(filtered_expected_scores)
            adjusted_rating = update_elo_rating(rating, actual_score, expected_score_avg, games_played, player)

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
    return 1 / (1 + 10 ** ((opponent_rating - rating) / 150))

def update_elo_rating(current_rating, actual_score, expected_score, games_played, player):
    match games_played:
        case games_played if games_played > 50:
            adjustment_factor = 15
        case games_played if games_played <= 50 & games_played > 30:
            adjustment_factor = 40
        case games_played if games_played <= 30 & games_played > 10:
            adjustment_factor = 75
        case games_played if games_played <= 10 & games_played > 3:
            adjustment_factor = 150
        case _:
            adjustment_factor = 55
    value =  adjustment_factor * (actual_score - expected_score)
    if value > 0:
        return current_rating + value
    else:
        return current_rating + value/(player-1)
