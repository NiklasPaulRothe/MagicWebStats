from urllib.parse import urlparse

import redis
import rq
from flask import Flask
from flask_principal import Principal, Permission, RoleNeed

from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from logging.handlers import RotatingFileHandler

import os
import logging

db = SQLAlchemy()
migrate = Migrate()
login = LoginManager()
login.login_view = 'auth.login'
principals = Principal()
admin_permission = Permission(RoleNeed('admin'))


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    url = urlparse(os.environ.get("REDIS_URL"))
    app.redis = redis.Redis(host=url.hostname, port=url.port, password=url.password, ssl=(url.scheme == "rediss"),
                    ssl_cert_reqs=None)
    app.task_queue = rq.Queue('magicstats-tasks', connection=app.redis)

    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)
    principals.init_app(app)

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.errors import bp as errors_bp
    app.register_blueprint(errors_bp)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.stats import bp as stats_bp
    app.register_blueprint(stats_bp)

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from app.decks import bp as decks_bp
    app.register_blueprint(decks_bp, url_prefix='/decks')

    from app.third_party_data import bp as third_party_bp
    app.register_blueprint(third_party_bp)

    from app.cards import bp as cards_bp
    app.register_blueprint(cards_bp)

    if not app.debug and not app.testing:
        if app.config['LOG_TO_STDOUT']:
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.INFO)
            app.logger.addHandler(stream_handler)

        if not os.path.exists('logs'):
            os.mkdir('logs')
        file_handler = RotatingFileHandler('logs/webstats.log', maxBytes=10240,
                                        backupCount=10)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)

        app.logger.setLevel(logging.INFO)
        app.logger.info('Webstats startup')

    return app

from app import models
