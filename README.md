# Inventory Management System (minimal Flask app)

This is a minimal Flask web application that serves a homepage for an inventory system.

To run locally:

1. Create and activate a Python virtual environment (Windows PowerShell):

```
python -m venv .venv; .\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```
pip install -r requirements.txt
```

3. Run the app:

```
python app.py
```

Open http://127.0.0.1:5000 in your browser. The homepage will show: "Inventory System Home Page"

Persistence
-----------
This app stores all data (users, products, sales, purchases) in a single SQLite database file named
`inventory.db` located in the project root directory beside `app.py`. When you run the app normally, the
database file will be created automatically if it doesn't exist.
 
Notes on schema changes and migrations
------------------------------------
If you change the models or database schema (for example adding new columns like `purchase.remaining`),
it's recommended to use a proper migration tool such as Flask-Migrate (Alembic) to create and apply
migrations rather than relying on runtime ALTER attempts. For local development the app will create
`inventory.db` automatically, but for production or when upgrading the schema, add migrations to avoid
data loss and keep schema changes reproducible.

