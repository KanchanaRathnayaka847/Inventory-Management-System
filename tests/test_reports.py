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


def test_reports_page_requires_login(client):
    resp = client.get('/reports', follow_redirects=False)
    assert resp.status_code in (301, 302)


def test_reports_page_renders_after_login(client):
    # signup/login
    client.post('/signup', data={'username': 'repouser', 'password': 'pw'}, follow_redirects=True)
    client.post('/login', data={'username': 'repouser', 'password': 'pw'}, follow_redirects=True)

    rv = client.get('/reports')
    assert rv.status_code == 200
    assert b'Reports & Dashboard' in rv.data
    assert b'Sales Data' in rv.data
    assert b'Purchase Data' in rv.data
    assert b'Profit / Loss' in rv.data


def test_reports_subpages_render_after_login(client):
    client.post('/signup', data={'username': 'u2', 'password': 'pw'}, follow_redirects=True)
    client.post('/login', data={'username': 'u2', 'password': 'pw'}, follow_redirects=True)

    r1 = client.get('/reports/sales')
    assert r1.status_code == 200
    assert b'Sales Dashboard' in r1.data

    r2 = client.get('/reports/purchases')
    assert r2.status_code == 200
    assert b'Purchase Dashboard' in r2.data

    r3 = client.get('/reports/profit-loss')
    assert r3.status_code == 200
    assert b'Profit / Loss Dashboard' in r3.data
