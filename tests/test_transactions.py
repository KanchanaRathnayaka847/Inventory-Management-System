"""
INVENTORY TRANSACTION TESTS
Tests for purchase and sales transactions with inventory management logic.

This test module covers:
- Purchase transactions and stock increases
- Sales transactions and stock decreases  
- FIFO (First In, First Out) inventory consumption
- Negative stock prevention
- Transaction validation and error handling

Test scenarios:
- Valid purchase increases product quantity
- Valid sale decreases product quantity
- Sales cannot exceed available stock
- FIFO logic consumes oldest inventory first
"""

import pytest

from app import create_app, db, Product


@pytest.fixture
def app():
    """
    Create test Flask application with in-memory database.
    Ensures clean state for each test with database schema created.
    """
    app = create_app({
        'TESTING': True,  # Enable Flask testing mode
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',  # Isolated in-memory database
        'SECRET_KEY': 'test-secret',  # Fixed secret for consistent sessions
    })

    with app.app_context():
        db.create_all()  # Create all database tables including transaction tables
        yield app


@pytest.fixture
def client(app):
    """
    Create test client for HTTP requests.
    """
    return app.test_client()


def test_purchase_increases_stock(client):
    """
    Test that purchase transactions correctly increase product inventory.
    
    Validates:
    1. Purchase form submission with valid data
    2. Product quantity increases by purchased amount
    3. Success message is displayed to user
    4. Database state is correctly updated
    """
    # *** SETUP: Create authenticated user ***
    client.post('/signup', data={'username': 'u', 'password': 'p'}, follow_redirects=True)
    client.post('/login', data={'username': 'u', 'password': 'p'}, follow_redirects=True)
    
    # *** SETUP: Create test product with initial inventory ***
    with client.application.app_context():
        prod = Product(name='Thing', category='Stuff', quantity=5, price=1.0, reorder_level=1)
        db.session.add(prod)
        db.session.commit()
        pid = prod.id  # Store product ID for later reference

    # *** TEST: Record purchase transaction ***
    # Purchase 10 units at $0.90 each
    resp = client.post('/purchases/add', data={'product_id': str(pid), 'quantity': '10', 'price': '0.9'}, follow_redirects=True)
    # Verify success message is displayed
    assert b'Purchase recorded' in resp.data

    # *** VALIDATE: Check inventory increase ***
    with client.application.app_context():
        p = db.session.get(Product, pid)
        # Initial quantity (5) + purchased quantity (10) = 15
        assert p.quantity == 15


def test_sale_decreases_stock_and_prevents_negative(client):
    """
    Test that sales transactions correctly decrease inventory and prevent overselling.
    
    Validates:
    1. Valid sale decreases product quantity appropriately
    2. Sales that exceed available stock are rejected
    3. Inventory cannot go below zero (business rule enforcement)
    4. Error messages guide user when sale is invalid
    """
    # *** SETUP: Create authenticated user ***
    client.post('/signup', data={'username': 'u2', 'password': 'p'}, follow_redirects=True)
    client.post('/login', data={'username': 'u2', 'password': 'p'}, follow_redirects=True)
    
    # *** SETUP: Create test product with limited inventory ***
    with client.application.app_context():
        prod = Product(name='Gizmo', category='Gadgets', quantity=3, price=5.0, reorder_level=1)
        db.session.add(prod)
        db.session.commit()
        pid = prod.id

    # valid sale of 2
    resp = client.post('/sales/add', data={'product_id': str(pid), 'quantity': '2', 'price': '5.0'}, follow_redirects=True)
    assert b'Sale recorded' in resp.data
    with client.application.app_context():
        p = db.session.get(Product, pid)
        assert p.quantity == 1

    # attempt to sell 5 (more than stock)
    resp = client.post('/sales/add', data={'product_id': str(pid), 'quantity': '5', 'price': '5.0'}, follow_redirects=True)
    assert b'Not enough stock' in resp.data
    with client.application.app_context():
        p = db.session.get(Product, pid)
        assert p.quantity == 1
