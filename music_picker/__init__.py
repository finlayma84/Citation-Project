from urllib.parse import quote
from flask import Flask

from .db import close_db
from .routes import bp


def create_app():
    app = Flask(__name__)
    app.config.from_mapping(DB_PATH='repertoire.db')
    app.jinja_env.filters['urlencode'] = quote
    app.teardown_appcontext(close_db)
    app.register_blueprint(bp)
    return app
