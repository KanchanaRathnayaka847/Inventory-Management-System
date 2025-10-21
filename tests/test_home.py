import pytest

from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_homepage(client):
    # Sign up and login first since home now requires authentication
    client.post('/signup', data={'username': 'homeuser', 'password': 'pw'}, follow_redirects=True)
    client.post('/login', data={'username': 'homeuser', 'password': 'pw'}, follow_redirects=True)

    rv = client.get('/')
    assert rv.status_code == 200
    assert b'Inventory System Home Page' in rv.data


