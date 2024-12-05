from app import db
from app.api import bp
from flask import jsonify
from flask_login import current_user, login_required
from sqlalchemy import text
import sqlalchemy as sa

from app.models import Player


@bp.route('/data')
@login_required
def data():
    results = db.session.execute(text(''' SELECT "Name" AS name,
    ( SELECT count(*) AS count
           FROM data_owner."Participants"
          WHERE "Participants".player_id = "Player".id) AS games,
    ( SELECT count(*) AS count
           FROM data_owner."Participants"
          WHERE "Participants".player_id = "Player".id AND "Participants"."Early Sol Ring" = true) AS "Early Sol Ring",
    ( SELECT COALESCE((( SELECT count(*)::double precision AS count
                   FROM data_owner."Participants"
                  WHERE "Participants".player_id = "Player".id AND "Participants"."Early Sol Ring" = true)) * 100::double precision / NULLIF(( SELECT count(*)::double precision AS count
                   FROM data_owner."Participants"
                     LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
                  WHERE "Participants".player_id = "Player".id AND "Games"."Date" > '2024-04-19'::date), 0::double precision), 0::double precision)::numeric(10,2) AS "coalesce") AS "Sol Ring (in%)",
    ( SELECT count(*) AS count
           FROM data_owner."Games"
          WHERE "Games"."Winner" = "Player".id) AS winner,
    ( SELECT COALESCE((( SELECT count(*)::double precision AS count
                   FROM data_owner."Games"
                  WHERE "Games"."Winner" = "Player".id)) * 100::double precision / NULLIF(( SELECT count(*)::double precision AS count
                   FROM data_owner."Participants"
                   LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
                  WHERE "Participants".player_id = "Player".id), 0::double precision), 0::double precision)::numeric(10,2) AS "coalesce") AS "winrate (in%)",
    ( SELECT count(*) AS count
           FROM data_owner."Games"
          WHERE "Games"."First_Player" = "Player".id) AS first,
    (SELECT COALESCE((( SELECT count(*)::double precision AS count
           FROM data_owner."Games"
          WHERE "Games"."First_Player" = "Player".id)) * 100::double precision / NULLIF(( SELECT count(*)::double precision AS count
           FROM data_owner."Participants"
          WHERE "Participants".player_id = "Player".id), 0::double precision), 0::double precision)::numeric(10,2) AS "coalesce") AS "first (in%)"
   FROM data_owner."Player";'''))

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
          WHERE "Decks"."Color_Identity" = "Color_Identities"."Name") AS games,
    ( SELECT count(*) AS count
           FROM data_owner."Participants"
             LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
             LEFT JOIN data_owner."Decks" ON "Decks".id = "Participants".deck_id
          WHERE "Games"."Winner" = "Participants".player_id AND "Decks"."Color_Identity" = "Color_Identities"."Name") AS wins,
    ((( SELECT count(*) AS count
           FROM data_owner."Participants"
             LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
             LEFT JOIN data_owner."Decks" ON "Decks".id = "Participants".deck_id
          WHERE "Games"."Winner" = "Participants".player_id AND "Decks"."Color_Identity" = "Color_Identities"."Name"))::double precision * 100::double precision / NULLIF(( SELECT count(*) AS count
           FROM data_owner."Participants"
             LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
             LEFT JOIN data_owner."Decks" ON "Decks".id = "Participants".deck_id
          WHERE "Decks"."Color_Identity" = "Color_Identities"."Name"), 0)::double precision)::numeric(10,2) AS "winrate (in%)"
   FROM data_owner."Color_Identities"
  WHERE NULLIF(( SELECT count(*) AS count
           FROM data_owner."Participants"
             LEFT JOIN data_owner."Games" ON "Games".id = "Participants".game_id
             LEFT JOIN data_owner."Decks" ON "Decks".id = "Participants".deck_id
          WHERE "Decks"."Color_Identity" = "Color_Identities"."Name"), 0)::numeric(10,2) IS NOT NULL;'''))

    list = []
    for entry in results:
        dict = {"Name": [], "Games": [], "Wins": [], "Winrate (in %)": []}
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
    "Decks".elo_rating AS elo
   FROM data_owner."Decks",
    data_owner."Player"
  WHERE "Decks"."Player" = "Player".id AND "Decks"."Active" = true
  ORDER BY "Decks"."Commander";'''))

    list = []
    for entry in results:
        dict = {"Deckname": [], "Spieler": [], "Commander": [], "Farbe": [], "Spiele": [], "Siege": [],
                "Winrate (in %)": []}
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
        list.append(dict)

    return jsonify(list)

@bp.route('/userdecks')
@login_required
def userdecks():
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
            )::numeric(10,2)
    FROM "data_owner"."Decks"
    WHERE "Player" = :player AND "Active" = true
    ORDER BY "Name";'''),
        {'player': db.session.scalar(sa.select(Player.id).where(current_user.spieler == Player.id))})

    list = []
    for entry in results:
        dict = {"Name": [], "Commander": [], "Color Identity": [], "Spiele": [], "Zuletzt gespielt": [], "Siege": [],
                "Winrate (in %)": []}
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
        list.append(dict)

    return jsonify(list)