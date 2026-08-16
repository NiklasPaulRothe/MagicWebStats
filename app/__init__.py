
from flask import Flask
from flask_principal import Principal, Permission, RoleNeed

from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
login = LoginManager()
login.login_view = 'auth.login'
principals = Principal()
admin_permission = Permission(RoleNeed('admin'))


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

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

    return app
