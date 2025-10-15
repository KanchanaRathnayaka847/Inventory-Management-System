import pytest

from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_homepage(client):
    rv = client.get('/')
    assert rv.status_code == 200
    assert b'Inventory System Home Page' in rv.data


