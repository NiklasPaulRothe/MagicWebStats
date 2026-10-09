import logging
import time
import traceback

import pyrchidekt
import requests
from flask import redirect, url_for
from flask_login import login_required
from pyrchidekt.api import getDeckById

from app import db, third_party_data
from app.auth import role_required
from app.models import DeckComponent, Deck, DeckTag
from app.third_party_data import bp

logger = logging.getLogger(__name__)

MOXFIELD_API_BASE = 'https://api2.moxfield.com/v2'
# Moxfield sits behind Cloudflare and rejects requests without a browser-like
# User-Agent, so we send one explicitly.
MOXFIELD_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
}


def get_id_from_url(url):
    if 'archidekt' in url:
        splitted = url.split('/')
        next = False
        for i in splitted:
            if next == True:
                return ('archidekt', i)
            if i == 'decks':
                next = True
        return None

    if 'moxfield' in url:
        splitted = url.split('/')
        next = False
        for i in splitted:
            if next == True and i != '':
                return ('moxfield', i)
            if i == 'decks':
                next = True
        return None

    return None

def load_cards_from_archidekt(archidekt_id, deck_id):
    logger.info('load cards...')
    logger.info(archidekt_id)
    try:
        deck = pyrchidekt.api.getDeckById(archidekt_id.strip())
    except Exception as e:
        logger.error("Failed to load deck %s: %s", archidekt_id, e)
        return
    deck_categories = deck.categories

    Cards = DeckComponent.query.filter(DeckComponent.deck_id == deck_id).all()
    for card in Cards:
        db.session.delete(card)

    for card in deck.cards:
        try:
            in_deck = False
            for category in card.categories:
                for deck_category in deck_categories:
                    if category == deck_category.name and deck_category.included_in_deck:
                        in_deck = True
            if in_deck:
                component = DeckComponent(
                    deck_id = deck_id,
                    card_id = card.card.uid,
                    name = card.card.oracle_card.name,
                    count = card.quantity
                )
                db.session.add(component)
        except Exception as e:
            name = card.card.oracle_card.name
            logger.error('%s could not be found: %s', name, traceback.format_exc())
            continue
    
    # Handle deck tags
    try:
        # Get tags from the Archidekt deck object
        deck_tags = getattr(deck, 'deck_tags', [])
        logger.info(deck_tags)
        
        # Delete all existing tags for this deck
        existing_tags = DeckTag.query.filter(DeckTag.deck_id == deck_id).all()
        for tag in existing_tags:
            db.session.delete(tag)
        
        # Add new tags
        if deck_tags:
            for tag in deck_tags:
                logger.info(tag)
                deck_tag = DeckTag(
                    deck_id=deck_id,
                    tag=tag['name'].strip()
                )
                db.session.add(deck_tag)
            logger.info('Saved %d tags for deck %s', len(deck_tags), deck_id)
    except Exception as e:
        logger.error('Error saving tags for deck %s: %s%s', deck_id, str(e), traceback.format_exc())
    
    try:
        db.session.commit()
    except Exception as e:
        logger.error("Something went wrong while committing to the database for %s: %s", deck.name, e)
        db.session.rollback()
    logger.info('end load cards....')
    return redirect(url_for('main.index'), code=302)


def load_cards_from_moxfield(moxfield_id, deck_id):
    logger.info('load cards...')
    logger.info(moxfield_id)
    try:
        response = requests.get(
            '%s/decks/all/%s' % (MOXFIELD_API_BASE, moxfield_id.strip()),
            headers=MOXFIELD_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        deck = response.json()
    except Exception as e:
        logger.error("Failed to load deck %s: %s", moxfield_id, e)
        return

    Cards = DeckComponent.query.filter(DeckComponent.deck_id == deck_id).all()
    for card in Cards:
        db.session.delete(card)

    # Moxfield splits a deck into several named "boards", each a dict keyed by
    # card name whose value holds `quantity` and a nested `card` object. Unlike
    # Archidekt (where every card carries categories and we filter by
    # `included_in_deck`), Moxfield already separates the real deck from
    # non-deck piles via these board names. The boards that make up the actual
    # deck are commanders, mainboard, companions and signatureSpells; the
    # sideboard, maybeboard, attractions, stickers and tokens are intentionally
    # excluded.
    for board_name in ('commanders', 'mainboard', 'companions', 'signatureSpells'):
        board = deck.get(board_name) or {}
        for card_name, entry in board.items():
            try:
                card = entry.get('card', {})
                component = DeckComponent(
                    deck_id=deck_id,
                    card_id=card.get('scryfall_id'),
                    name=card.get('name', card_name),
                    count=entry.get('quantity', 1)
                )
                db.session.add(component)
            except Exception as e:
                logger.error('%s could not be found: %s', card_name, traceback.format_exc())
                continue

    # Handle deck tags
    try:
        # Moxfield has no single flat "tags" list like Archidekt's deck_tags.
        # User-applied tags live in `authorTags`, which is an object/map of
        # category -> list of tag strings (e.g. {"Archetype": ["Combo"]}).
        # Moxfield's curated categories live in `hubs`, a list of objects with
        # a `name`. We flatten both into individual tag strings. The parsing is
        # defensive because an empty deck returns authorTags={} and hubs=[], and
        # the populated shape is only loosely documented.
        deck_tags = []

        author_tags = deck.get('authorTags') or {}
        if isinstance(author_tags, dict):
            for values in author_tags.values():
                if isinstance(values, (list, tuple)):
                    deck_tags.extend(str(v) for v in values)
                else:
                    deck_tags.append(str(values))
        elif isinstance(author_tags, (list, tuple)):
            deck_tags.extend(str(v) for v in author_tags)

        for hub in deck.get('hubs') or []:
            if isinstance(hub, dict):
                name = hub.get('name')
                if name:
                    deck_tags.append(str(name))
            elif hub:
                deck_tags.append(str(hub))

        logger.info(deck_tags)

        # Delete all existing tags for this deck
        existing_tags = DeckTag.query.filter(DeckTag.deck_id == deck_id).all()
        for tag in existing_tags:
            db.session.delete(tag)

        # Add new tags (de-duplicated, preserving order)
        seen = set()
        for tag in deck_tags:
            tag = tag.strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            logger.info(tag)
            deck_tag = DeckTag(
                deck_id=deck_id,
                tag=tag
            )
            db.session.add(deck_tag)
        if seen:
            logger.info('Saved %d tags for deck %s', len(seen), deck_id)
    except Exception as e:
        logger.error('Error saving tags for deck %s: %s%s', deck_id, str(e), traceback.format_exc())

    try:
        db.session.commit()
    except Exception as e:
        logger.error("Something went wrong while committing to the database for %s: %s", deck.get('name'), e)
        db.session.rollback()
    logger.info('end load cards....')
    return redirect(url_for('main.index'), code=302)

@bp.route('/LoadAllDecks', methods=['GET'])
@role_required('admin')
@login_required
def load_all_decks():
    decks = Deck.query.all()
    for deck in decks:
        if not deck.decklist == None and deck.decksite == None:
            deckbuilder = third_party_data.deckbuilder.get_id_from_url(deck.decklist)
            if deckbuilder is None:
                logger.warning("Could not extract deck ID from URL: %s", deck.decklist)
                continue
            deck.decksite = deckbuilder[0].strip()
            deck.archidekt_id = deckbuilder[1].strip()
            db.session.commit()
        if not deck.decksite == None:
            try:
                if 'archidekt' in deck.decksite:
                    load_cards_from_archidekt(deck.archidekt_id.strip(), deck.id)
                    time.sleep(1)
                elif 'moxfield' in deck.decksite:
                    load_cards_from_moxfield(deck.archidekt_id.strip(), deck.id)
                    time.sleep(1)
            except Exception as e:
                logger.error("Error loading deck %s: %s", deck.id, e)
                deck.decksite = None
                deck.archidekt_id = None
                db.session.commit()

    return redirect(url_for('main.index'), code=302)
