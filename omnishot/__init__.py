import logging

from flask import Flask

from . import paths

logging.getLogger('werkzeug').setLevel(logging.ERROR)


def create_app():
    app = Flask(
        __name__,
        template_folder=paths.TEMPLATE_FOLDER,
        static_folder=paths.STATIC_FOLDER,
    )

    from . import routes
    routes.register(app)

    return app
