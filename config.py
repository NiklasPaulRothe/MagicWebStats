import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(dotenv_path=os.path.join(basedir, '.env'))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "The application cannot start without a secret key."
        )
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', '').replace(
        'postgres://', 'postgresql://')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_size': 5,
        'pool_recycle': 300,
    }
    SESSION_COOKIE_DOMAIN = False
    PERSONAL_STATS_USERNAME = os.environ.get('PERSONAL_STATS_USERNAME', 'Niklas')
    DB_SCHEMA = os.environ.get('DB_SCHEMA', 'magic_stats_owner')


class TestingConfig:
    """Configuration for testing and local development (SQLite in-memory)."""

    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_DOMAIN = False
    PERSONAL_STATS_USERNAME = 'Niklas'
    DB_SCHEMA = 'magic_stats_owner'
