import os

from dotenv import load_dotenv
from openskill.models import PlackettLuce
import psycopg2


# Participants has to be tuple List of Player and deck
def calculate_skill(Participants, Winner):
    load_dotenv()
    conn = psycopg2.connect(os.environ.get('DATABASE_URL', '').replace(
        'postgres://', 'postgresql://'))
    model = PlackettLuce()

    player_list = []
    player_list_sorted= []
    for participant in Participants:
        win = False
        # Mu and Sigma is created in the database when creating a deck
        cur = conn.cursor()
        cur.execute("SELECT mu, sigma FROM data_owner.skill_level WHERE \"Player\" = %s and \"Deck\" = %s", (participant[0], participant[1]))

        if participant[0] == Winner:
            win = True

        # if deck, player combination is not in database (borrowed deck) assume new player
        data = cur.fetchone()
        rating = None
        if data != None:
            rating = model.create_rating([float(data[0]), data[1]])
        else:
            rating = model.rating(mu=25, sigma=8.333)
        if not win:
            player_list.append({
                        "Player": participant[0],
                        "Deck": participant[1],
                        "Winner": win,
                        "in_database": True,
                        "rating": rating})
        else:
            player_list_sorted.append({
                        "Player": participant[0],
                        "Deck": participant[1],
                        "Winner": win,
                        "in_database": True,
                        "rating": rating})
        cur.close()
    for player in player_list:
        player_list_sorted.append(player)

    if len(player_list_sorted) == 3:
        p1 = player_list_sorted[0]['rating']
        p2 = player_list_sorted[1]['rating']
        p3 = player_list_sorted[2]['rating']

        ranks = [1,2,2]
        match = [[p1], [p2], [p3]]
        [[p1], [p2], [p3]] = model.rate(match, ranks=ranks)

        player_list_sorted[0]['rating'] = p1
        player_list_sorted[1]['rating'] = p2
        player_list_sorted[2]['rating'] = p3

    elif len(player_list_sorted) == 4:
        p1 = player_list_sorted[0]['rating']
        p2 = player_list_sorted[1]['rating']
        p3 = player_list_sorted[2]['rating']
        p4 = player_list_sorted[3]['rating']

        ranks = [1,2,2,2]
        match = [[p1], [p2], [p3], [p4]]
        [[p1], [p2], [p3], [p4]] = model.rate(match, ranks=ranks)

        player_list_sorted[0]['rating'] = p1
        player_list_sorted[1]['rating'] = p2
        player_list_sorted[2]['rating'] = p3
        player_list_sorted[3]['rating'] = p4

    elif len(player_list_sorted) == 5:
        p1 = player_list_sorted[0]['rating']
        p2 = player_list_sorted[1]['rating']
        p3 = player_list_sorted[2]['rating']
        p4 = player_list_sorted[3]['rating']
        p5 = player_list_sorted[4]['rating']

        ranks = [1,2,2,2, 2]
        match = [[p1], [p2], [p3], [p4], [p5]]
        [[p1], [p2], [p3], [p4], [p5]] = model.rate(match, ranks=ranks)

        player_list_sorted[0]['rating'] = p1
        player_list_sorted[1]['rating'] = p2
        player_list_sorted[2]['rating'] = p3
        player_list_sorted[3]['rating'] = p4
        player_list_sorted[4]['rating'] = p5

    for player in player_list_sorted:
        if player['in_database']:
            cur = conn.cursor()
            cur.execute("UPDATE data_owner.skill_level SET mu = %s, sigma = %s WHERE \"Player\" = %s and \"Deck\" = %s",
                        (player['rating'].mu, player['rating'].sigma, player['Player'], player['Deck']))
    conn.commit()

if __name__ == '__main__':
    load_dotenv()
    conn = psycopg2.connect(os.environ.get('DATABASE_URL', '').replace(
        'postgres://', 'postgresql://'))
    cur = conn.cursor()
    cur.execute("SELECT id, \"Winner\" FROM data_owner.\"Games\"")
    games = cur.fetchall()

    cur.execute("SELECT game_id, player_id, deck_id FROM data_owner.\"Participants\"")
    participants = cur.fetchall()

    for game in games:
        participant_list = []
        winner = game[1]
        for participant in participants:
            if participant[0] == game[0]:
                participant_list.append((participant[1], participant[2]))
        calculate_skill(participant_list, winner)