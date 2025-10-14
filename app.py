from flask import Flask


def create_app():
    """Create and return a minimal Flask application."""
    app = Flask(__name__)

    @app.route('/')
    def home():
        return 'Inventory System Home Page'

    return app


if __name__ == '__main__':
    # Run locally for development
    create_app().run(debug=True, host='127.0.0.1', port=5000)
