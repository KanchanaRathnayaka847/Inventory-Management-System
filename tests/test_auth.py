import pytest

from app import create_app, db, User


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


def test_signup_and_login(client):
    # Sign up
    resp = client.post('/signup', data={'username': 'alice', 'password': 'wonderland'}, follow_redirects=True)
    assert b'Account created successfully' in resp.data

    # Login with correct credentials
    resp = client.post('/login', data={'username': 'alice', 'password': 'wonderland'}, follow_redirects=True)
    assert b'ABC Company' in resp.data

    # Logout
    resp = client.get('/logout', follow_redirects=True)
    assert b'You have been logged out' in resp.data
