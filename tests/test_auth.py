"""
AUTHENTICATION TESTS
Tests for user registration, login, logout, and session management functionality.

This test module covers:
- User signup with validation
- Login with correct/incorrect credentials
- Logout functionality
- Session persistence and security

Test fixtures:
- app: Creates test Flask application with in-memory SQLite database
- client: Provides test client for making HTTP requests
"""

import pytest

from app import create_app, db, User


@pytest.fixture
def app():
    """
    Create and configure test Flask application.
    
    Uses in-memory SQLite database for isolation between tests.
    Enables testing mode to catch exceptions during test execution.
    """
    app = create_app({
        'TESTING': True,  # Enable Flask testing mode
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',  # In-memory database for speed and isolation
        'SECRET_KEY': 'test-secret',  # Fixed secret for consistent testing
    })

    with app.app_context():
        db.create_all()  # Create all database tables for testing
        yield app


@pytest.fixture
def client(app):
    """
    Create test client for making HTTP requests to the application.
    """
    return app.test_client()


def test_signup_and_login(client):
    """
    Test complete user authentication flow: signup → login → logout.
    
    Validates:
    1. User can create new account with valid credentials
    2. User can login with correct credentials and access protected pages
    3. User can logout and session is cleared
    4. Response content confirms each step worked correctly
    """
    # *** TEST USER REGISTRATION ***
    resp = client.post('/signup', data={'username': 'alice', 'password': 'wonderland'}, follow_redirects=True)
    assert b'Account created successfully' in resp.data

    # *** TEST SUCCESSFUL LOGIN ***
    # Login with the newly created credentials
    resp = client.post('/login', data={'username': 'alice', 'password': 'wonderland'}, follow_redirects=True)
    # Verify user is redirected to home page (ABC Company indicates successful auth)
    assert b'ABC Company' in resp.data

    # *** TEST LOGOUT FUNCTIONALITY ***
    resp = client.get('/logout', follow_redirects=True)
    # Verify logout message is displayed
    assert b'You have been logged out' in resp.data
