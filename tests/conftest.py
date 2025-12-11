# tests/conftest.py
import pytest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import app, get_db_connection




@pytest.fixture
def client():
    """
    Flask test-klient.
    """
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def test_borger_id():
    """
    Opretter en test-borger i databasen og returnerer dens id.
    Bruges i tests til at indsætte events.
    """
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO borger (navn, telefon, adresse, vaerelse)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                    """,
                    ("Test Borger", "00000000", "Testvej 1", "101"),
                )
                borger_id = cur.fetchone()[0]
    finally:
        conn.close()

    assert isinstance(borger_id, int)
    return borger_id
