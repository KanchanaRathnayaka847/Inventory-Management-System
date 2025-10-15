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


def test_add_edit_delete_product(client):
    # Register and login first (routes require login for modifications)
    client.post('/signup', data={'username': 'manager', 'password': 'secret'}, follow_redirects=True)
    client.post('/login', data={'username': 'manager', 'password': 'secret'}, follow_redirects=True)

    # Add
    resp = client.post('/products/add', data={
        'name': 'Widget',
        'category': 'Gadgets',
        'quantity': '10',
        'price': '2.50',
        'reorder_level': '3',
    }, follow_redirects=True)
    assert b'Product added' in resp.data
    assert b'Widget' in resp.data

    # Get product id
    with client.application.app_context():
        p = Product.query.filter_by(name='Widget').first()
        assert p is not None
        pid = p.id

    # Edit
    resp = client.post(f'/products/{pid}/edit', data={
        'name': 'Widget Pro',
        'category': 'Gadgets',
        'quantity': '15',
        'price': '3.75',
        'reorder_level': '5',
    }, follow_redirects=True)
    assert b'Product updated' in resp.data
    assert b'Widget Pro' in resp.data

    # Delete
    resp = client.post(f'/products/{pid}/delete', follow_redirects=True)
    assert b'Product deleted' in resp.data
    assert b'Widget Pro' not in resp.data
