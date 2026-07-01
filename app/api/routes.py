from app import db
from app.api import bp
from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import text, func
import sqlalchemy as sa

from app.auth import role_required
from app.models import Player, User, Color, ColorComponent, Deck, Card, ColorIdentity


@bp.route('/data')
@login_required
def data():
    results = db.session.execute(text(''' SELECT "Name" AS name,
    ( SELECT count(*) AS count
           FROM data_owner."Participants"
        LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
          WHERE "Participants".player_id = "Player".id
          AND "Games".cedh = False) AS games,
    ( SELECT count(*) AS count
           FROM data_owner."Participants"
          WHERE "Participants".player_id = "Player".id AND "Participants"."early_sol_ring" = true) AS "early_sol_ring",
    ( SELECT COALESCE((( SELECT count(*)::double precision AS count
                   FROM data_owner."Participants"
                  WHERE "Participants".player_id = "Player".id AND "Participants"."early_sol_ring" = true)) * 100::double precision / NULLIF(( SELECT count(*)::double precision AS count
                   FROM data_owner."Participants"
                     LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
                  WHERE "Participants".player_id = "Player".id AND "Games"."Date" > '2024-04-19'::date), 0::double precision), 0::double precision)::numeric(10,2) AS "coalesce") AS "Sol Ring (in%)",
    ( SELECT count(*) AS count
           FROM data_owner."Games"
          WHERE "Games"."Winner" = "Player".id
          AND "Games".cedh = False) AS winner,
    ( SELECT COALESCE((( SELECT count(*)::double precision AS count
                   FROM data_owner."Games"
                  WHERE "Games"."Winner" = "Player".id
          AND "Games".cedh = False)) * 100::double precision / NULLIF(( SELECT count(*)::double precision AS count
                   FROM data_owner."Participants"
                   LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
                  WHERE "Participants".player_id = "Player".id), 0::double precision), 0::double precision)::numeric(10,2) AS "coalesce") AS "winrate (in%)",
    ( SELECT count(*) AS count
           FROM data_owner."Games"
          WHERE "Games"."First_Player" = "Player".id
          AND "Games".cedh = False) AS first,
    (SELECT COALESCE((( SELECT count(*)::double precision AS count
           FROM data_owner."Games"
          WHERE "Games"."First_Player" = "Player".id
          AND "Games".cedh = False)) * 100::double precision / NULLIF(( SELECT count(*)::double precision AS count
           FROM data_owner."Participants"
          WHERE "Participants".player_id = "Player".id), 0::double precision), 0::double precision)::numeric(10,2) AS "coalesce") AS "first (in%)"
   FROM data_owner."Player"
   WHERE "Player"."Name" != 'Precons';'''))

    list = []
    for entry in results:
        dict = {"Name": [], "Games": [], "Early Sol Ring": [], "Sol Ring (in %)": [], "Wins": [], "Winrate (in %)": [],
                "First": [], "First (in %)": []}
        dict["Name"].append(entry[0])
        dict["Games"].append(entry[1])
        dict["Early Sol Ring"].append(entry[2])
        dict["Sol Ring (in %)"].append(float(entry[3]))
        dict["Wins"].append(entry[4])
        dict["Winrate (in %)"].append(float(entry[5]))
        dict["First"].append(entry[6])
        dict["First (in %)"].append(float(entry[7]))
        list.append(dict)
    return jsonify(list)

@bp.route('/color-data')
@login_required
def color_data():
    results = db.session.execute(text('''  SELECT "Name" AS name,
    ( SELECT count(*) AS count
           FROM data_owner."Participants"
             LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
             LEFT JOIN data_owner."Decks" ON "Decks".id = "Participants".deck_id
          WHERE "Decks"."Color_Identity" = "Color_Identities"."Name"
          AND "Decks".cedh = False) AS games,
    ( SELECT count(*) AS count
           FROM data_owner."Participants"
             LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
             LEFT JOIN data_owner."Decks" ON "Decks".id = "Participants".deck_id
          WHERE "Games"."Winner" = "Participants".player_id AND "Decks"."Color_Identity" = "Color_Identities"."Name"
          AND "Decks".cedh = False) AS wins,
    ((( SELECT count(*) AS count
           FROM data_owner."Participants"
             LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
             LEFT JOIN data_owner."Decks" ON "Decks".id = "Participants".deck_id
          WHERE "Games"."Winner" = "Participants".player_id AND "Decks"."Color_Identity" = "Color_Identities"."Name"
          AND "Decks".cedh = False))::double precision * 100::double precision / NULLIF(( SELECT count(*) AS count
           FROM data_owner."Participants"
             LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
             LEFT JOIN data_owner."Decks" ON "Decks".id = "Participants".deck_id
          WHERE "Decks"."Color_Identity" = "Color_Identities"."Name"
          AND "Decks".cedh = False), 0)::double precision)::numeric(10,2) AS "winrate (in%)"
   FROM data_owner."Color_Identities"
  WHERE NULLIF(( SELECT count(*) AS count
           FROM data_owner."Participants"
             LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
             LEFT JOIN data_owner."Decks" ON "Decks".id = "Participants".deck_id
          WHERE "Decks"."Color_Identity" = "Color_Identities"."Name"
          AND "Decks".cedh = False), 0)::numeric(10,2) IS NOT NULL;'''))

    list = []
    colorless = Color.query.filter_by(Name='Colorless').first()
    colorless_img = colorless.img if colorless and colorless.img else None
    for entry in results:
        identity_name = entry[0]
        components = ColorComponent.query.filter_by(color_identity=identity_name).all()
        imgs = []
        for comp in components:
            color = Color.query.filter_by(Name=comp.color).first()
            if color and color.img:
                imgs.append(color.img)
        if not imgs and colorless_img:
            imgs = [colorless_img]
        dict = {"Name": [], "Games": [], "Wins": [], "Winrate (in %)": [], "ColorImgs": imgs}
        dict["Name"].append(entry[0])
        dict["Games"].append(entry[1])
        dict["Wins"].append(entry[2])
        dict["Winrate (in %)"].append(float(entry[3]))
        list.append(dict)
    return jsonify(list)

@bp.route('/deck-data')
@login_required
def deck_data():
    results = db.session.execute(text('''SELECT "Decks"."Name" AS deckname,
    "Player"."Name" AS spieler,
    "Decks"."Commander" || COALESCE(' + '::text || "Decks"."Partner", ''::text) AS commander,
    "Decks"."Color_Identity" AS farbe,
    ( SELECT count(*) AS count
           FROM data_owner."Participants"
          WHERE "Participants".deck_id = "Decks".id) AS spiele,
    ( SELECT count(*) AS count
           FROM data_owner."Games"
             LEFT JOIN data_owner."Participants" ON "Participants".game_id = "Games".id
          WHERE "Games"."Winner" = "Participants".player_id AND "Participants".deck_id = "Decks".id) AS siege,
    ((( SELECT count(*) AS count
           FROM data_owner."Games"
             LEFT JOIN data_owner."Participants" ON "Participants".game_id = "Games".id
          WHERE "Games"."Winner" = "Participants".player_id AND "Participants".deck_id = "Decks".id))::double precision * 100::double precision / NULLIF(( SELECT count(*) AS count
           FROM data_owner."Participants"
          WHERE "Participants".deck_id = "Decks".id), 0)::double precision)::numeric(10,2) AS "winrate (in%)",
    (SELECT round(avg(turns), 2) AS count
           FROM data_owner."Games"
             LEFT JOIN data_owner."Participants" ON "Participants".game_id = "Games".id
          WHERE "Games"."Winner" = "Participants".player_id AND "Participants".deck_id = "Decks".id),
    (SELECT count(*) AS count
           FROM data_owner."Games"
             LEFT JOIN data_owner."Participants" ON "Participants".game_id = "Games".id
          WHERE "Games"."Winner" = "Participants".player_id AND "Participants".deck_id = "Decks".id
            AND "Games".turns IS NOT NULL),
    "Decks".decklist AS decklist,
    "Decks".elo_rating AS elo,
    (SELECT array_agg(c.img ORDER BY c."Name")
           FROM data_owner.color_components cc
             JOIN data_owner."Colors" c ON c."Name" = cc.color
          WHERE cc.color_identity = "Decks"."Color_Identity"
            AND c.img IS NOT NULL) AS color_imgs,
    (SELECT array_agg(dt.tag ORDER BY dt.tag)
           FROM data_owner.deck_tags dt
          WHERE dt.deck_id = "Decks".id) AS tags
   FROM data_owner."Decks",
    data_owner."Player"
  WHERE "Decks"."Player" = "Player".id AND "Decks"."Active" = true
  ORDER BY "Decks"."Commander";'''))

    list = []
    for entry in results:
        dict = {"Deckname": [], "Spieler": [], "Commander": [], "Farbe": [], "Spiele": [], "Siege": [],
                "Winrate (in %)": [], "WTurns":[], "WTurnsCount": [], "Decklist": [], "elo": [], "ColorImgs": None, "Tags": []}
        dict["Deckname"].append(entry[0])
        dict["Spieler"].append(entry[1])
        dict["Commander"].append(entry[2])
        dict["Farbe"].append(entry[3])
        dict["Spiele"].append(entry[4])
        dict["Siege"].append(entry[5])
        if (entry[6] is not None):
            dict["Winrate (in %)"].append(float(entry[6]))
        else:
            dict["Winrate (in %)"].append("-")
        dict["WTurns"].append(entry[7])
        dict["WTurnsCount"].append(entry[8])
        dict["Decklist"].append(entry[9])
        dict["elo"].append(entry[10])
        dict["ColorImgs"] = entry[11] or []
        # Fallback to colorless symbol if no color images
        if not dict["ColorImgs"]:
            colorless = Color.query.filter_by(Name='Colorless').first()
            if colorless and colorless.img:
                dict["ColorImgs"] = [colorless.img]
        dict["Tags"] = entry[12] or []
        list.append(dict)

    return jsonify(list)

@bp.route('/userdecks/archive/<spieler>')
@login_required
def userdecks_archive(spieler):
    results = db.session.execute(text('''
    SELECT  "Decks".id,
            "Name", 
            "Commander", 
            "Color_Identity", 
            (   SELECT count(*) AS count 
                FROM "data_owner"."Participants"
                WHERE "Participants".deck_id = "Decks".id 
                AND "Participants".player_id = :player
            ),
            (   SELECT count(*) AS count
                FROM "data_owner"."Games"
                LEFT JOIN "data_owner"."Participants"   
                ON "Participants".game_id = "Games".id
                WHERE "Games"."Winner" = "Participants".player_id 
                AND "Participants".deck_id = "Decks".id  
                AND "Participants".player_id = :player  
            ),
            (   
                (
                    (   SELECT count(*) AS count
                        FROM "data_owner"."Games"
                        LEFT JOIN "data_owner"."Participants"   
                        ON "Participants".game_id = "Games".id
                        WHERE "Games"."Winner" = "Participants".player_id 
                        AND "Participants".deck_id = "Decks".id  
                        AND "Participants".player_id = :player))::double precision * 100::double precision / NULLIF(( SELECT count(*) AS count
                        FROM "data_owner"."Participants"
                        WHERE "Participants".deck_id = "Decks".id 
                        AND "Participants".player_id = :player
                    ),  
                    0
                )::double precision
            )::numeric(10,2),
            decklist,
            (SELECT array_agg(c.img ORDER BY c."Name")
             FROM data_owner.color_components cc
             JOIN data_owner."Colors" c ON c."Name" = cc.color
             WHERE cc.color_identity = "Decks"."Color_Identity"
               AND c.img IS NOT NULL) AS color_imgs
    FROM "data_owner"."Decks"
    WHERE "Player" = :player AND "Active" = false
    ORDER BY "Name";'''), {'player': spieler})

    list = []
    for entry in results:
        color_imgs = entry[8] or []
        if not color_imgs:
            colorless = Color.query.filter_by(Name='Colorless').first()
            if colorless and colorless.img:
                color_imgs = [colorless.img]
        winrate = float(entry[6]) if entry[6] is not None else None
        deck = {
            "id": entry[0],
            "Name": entry[1],
            "Commander": entry[2],
            "ColorImgs": color_imgs,
            "Spiele": entry[4],
            "Siege": entry[5],
            "Winrate (in %)": winrate,
            "Decklist": entry[7],
        }
        list.append(deck)

    return jsonify(list)


@bp.route('/userdecks/<spieler>')
@login_required
def userdecks(spieler):
    results = db.session.execute(text('''
    SELECT  "Name", 
            "Commander", 
            "Color_Identity", 
            (   SELECT count(*) AS count 
                FROM "data_owner"."Participants"
                WHERE "Participants".deck_id = "Decks".id 
                AND "Participants".player_id = :player
            ),
            (   SELECT max("Games"."Date") AS max
                FROM "data_owner"."Games"
                LEFT JOIN "data_owner"."Participants"   
                ON "Games".id = "Participants".game_id
                WHERE "Participants".deck_id = "Decks".id
            ),
            (   SELECT count(*) AS count
                FROM "data_owner"."Games"
                LEFT JOIN "data_owner"."Participants"   
                ON "Participants".game_id = "Games".id
                WHERE "Games"."Winner" = "Participants".player_id 
                AND "Participants".deck_id = "Decks".id  
                AND "Participants".player_id = :player  
            ),
            (   
                (
                    (   SELECT count(*) AS count
                        FROM "data_owner"."Games"
                        LEFT JOIN "data_owner"."Participants"   
                        ON "Participants".game_id = "Games".id
                        WHERE "Games"."Winner" = "Participants".player_id 
                        AND "Participants".deck_id = "Decks".id  
                        AND "Participants".player_id = :player))::double precision * 100::double precision / NULLIF(( SELECT count(*) AS count
                        FROM "data_owner"."Participants"
                        WHERE "Participants".deck_id = "Decks".id 
                        AND "Participants".player_id = :player
                    ),  
                    0
                )::double precision
            )::numeric(10,2),
            decklist,
            (SELECT array_agg(c.img ORDER BY c."Name")
             FROM data_owner.color_components cc
             JOIN data_owner."Colors" c ON c."Name" = cc.color
             WHERE cc.color_identity = "Decks"."Color_Identity"
               AND c.img IS NOT NULL) AS color_imgs,
            (SELECT array_agg(dt.tag ORDER BY dt.tag)
             FROM data_owner.deck_tags dt
             WHERE dt.deck_id = "Decks".id) AS tags
    FROM "data_owner"."Decks"
    WHERE "Player" = :player AND "Active" = true
    ORDER BY "Name";'''),{'player': spieler})

    list = []
    for entry in results:
        dict = {"Name": [], "Commander": [], "Color Identity": [], "Spiele": [], "Zuletzt gespielt": [], "Siege": [],
                "Winrate (in %)": [], "Decklist": [], "ColorImgs": None, "Tags": []}
        dict["Name"].append(entry[0])
        dict["Commander"].append(entry[1])
        dict["Color Identity"].append(entry[2])
        dict["Spiele"].append(entry[3])
        if(entry[4] is not None):
            dict["Zuletzt gespielt"].append(str(entry[4].day) + "." + str(entry[4].month) + "." + str(entry[4].year))
        else:
            dict["Zuletzt gespielt"].append("-")
        dict["Siege"].append(entry[5])
        if (entry[6] is not None):
            dict["Winrate (in %)"].append(float(entry[6]))
        else:
            dict["Winrate (in %)"].append("-")
        dict["Decklist"].append(entry[7])
        dict["ColorImgs"] = entry[8] or []
        # Fallback to colorless symbol if no color images
        if not dict["ColorImgs"]:
            colorless = Color.query.filter_by(Name='Colorless').first()
            if colorless and colorless.img:
                dict["ColorImgs"] = [colorless.img]
        dict["Tags"] = entry[9] or []
        list.append(dict)

    return jsonify(list)


@bp.route('/quick-add-player', methods=['POST'])
@role_required('admin')
@login_required
def quick_add_player():
    """Add a new player via AJAX. Returns the new player name on success."""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Name is required'}), 400

    name = data['name'].strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400

    # Check if player already exists
    existing = db.session.scalar(sa.select(Player).where(Player.Name == name))
    if existing:
        return jsonify({'error': 'Ein Spieler mit diesem Namen existiert bereits.'}), 409

    player = Player(Name=name)
    db.session.add(player)
    db.session.commit()

    return jsonify({'name': player.Name}), 201


@bp.route('/quick-add-deck', methods=['POST'])
@role_required('admin')
@login_required
def quick_add_deck():
    """Add a new deck via AJAX. Returns deck info on success."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    name = (data.get('name') or '').strip()
    commander = (data.get('commander') or '').strip()
    player_name = (data.get('player') or '').strip()
    color_identity = (data.get('color_identity') or '').strip()
    partner = (data.get('partner') or '').strip() or None
    cedh = bool(data.get('cedh', False))

    # Validate required fields
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not commander:
        return jsonify({'error': 'Commander is required'}), 400
    if not player_name:
        return jsonify({'error': 'Player is required'}), 400
    if not color_identity:
        return jsonify({'error': 'Color Identity is required'}), 400

    # Check deck name uniqueness
    existing_deck = db.session.scalar(sa.select(Deck).where(Deck.Name == name))
    if existing_deck:
        return jsonify({'error': 'Es gibt schon ein Deck mit diesem Namen.'}), 409

    # Validate commander exists in card database
    card = db.session.scalar(sa.select(Card).where(Card.Name == commander))
    if not card:
        return jsonify({'error': 'Der Commander existiert nicht in der Datenbank.'}), 400

    # Validate player exists
    player = db.session.scalar(sa.select(Player).where(Player.Name == player_name))
    if not player:
        return jsonify({'error': 'Spieler existiert nicht.'}), 400

    # Validate color identity exists
    ci = db.session.scalar(sa.select(ColorIdentity).where(ColorIdentity.Name == color_identity))
    if not ci:
        return jsonify({'error': 'Color Identity existiert nicht.'}), 400

    # Get commander image
    img = card.image_uri

    deck = Deck(
        Name=name,
        Commander=commander,
        Player=player.id,
        Color_Identity=color_identity,
        Partner=partner,
        image_uri=img,
        cedh=cedh,
        Version=1,
        patch=0,
        change=0,
        Last_Rework=func.current_date(),
        last_patch=func.current_date(),
        Last_Change=func.current_date()
    )
    db.session.add(deck)
    db.session.commit()

    return jsonify({
        'name': deck.Name,
        'commander': deck.Commander,
        'player': player_name
    }), 201
