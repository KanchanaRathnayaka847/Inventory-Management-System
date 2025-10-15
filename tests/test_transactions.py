import pytest

from app import create_app, db, Product


@pytest.fixture
def app():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-secret',
    })

    with app.app_context():
        db.create_all()
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


def test_purchase_increases_stock(client):
    # create product and user
    client.post('/signup', data={'username': 'u', 'password': 'p'}, follow_redirects=True)
    client.post('/login', data={'username': 'u', 'password': 'p'}, follow_redirects=True)
    # add product directly
    with client.application.app_context():
        prod = Product(name='Thing', category='Stuff', quantity=5, price=1.0, reorder_level=1)
        db.session.add(prod)
        db.session.commit()
        pid = prod.id

    # record purchase of 10
    resp = client.post('/purchases/add', data={'product_id': str(pid), 'quantity': '10', 'price': '0.9'}, follow_redirects=True)
    assert b'Purchase recorded' in resp.data

    with client.application.app_context():
        p = db.session.get(Product, pid)
        assert p.quantity == 15


def test_sale_decreases_stock_and_prevents_negative(client):
    client.post('/signup', data={'username': 'u2', 'password': 'p'}, follow_redirects=True)
    client.post('/login', data={'username': 'u2', 'password': 'p'}, follow_redirects=True)
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
