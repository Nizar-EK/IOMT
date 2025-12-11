# tests/test_app.py
import pytest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import get_db_connection




def _get_token(client, user_id: int = 1) -> str:
    """Hjælpefunktion til at hente token i tests."""
    response = client.post(f"/token/{user_id}")
    assert response.status_code == 200
    data = response.get_json()
    assert "token" in data
    token = data["token"]

    # Simpelt tjek: en JWT har 3 dele adskilt af punktummer
    parts = token.split(".")
    assert len(parts) == 3
    return token


def test_index_route_returns_message(client):
    """Test at / route virker og returnerer korrekt JSON."""
    response = client.get("/")
    assert response.status_code == 200

    data = response.get_json()
    assert "message" in data
    assert "Medibox API" in data["message"]


def test_get_token_valid_user(client):
    """Test at vi kan få en token for user 1."""
    response = client.post("/token/1")
    assert response.status_code == 200

    data = response.get_json()
    assert "token" in data
    assert isinstance(data["token"], str)


def test_get_token_invalid_user_returns_404(client):
    """Test at ukendt user id giver 404."""
    response = client.post("/token/9999")
    assert response.status_code == 404


def test_box_event_requires_auth(client, test_borger_id):
    """Uden Bearer-token skal /box-event afvise (401)."""
    payload = {"borger_id": test_borger_id, "box_open": True}
    response = client.post("/box-event", json=payload)
    assert response.status_code == 401  # unauthorized


def test_box_event_invalid_token(client, test_borger_id):
    """Hvis vi sender et ugyldigt token, skal vi også have 401."""
    headers = {"Authorization": "Bearer totalt-forkert-token"}
    payload = {"borger_id": test_borger_id, "box_open": True}
    response = client.post("/box-event", json=payload, headers=headers)
    assert response.status_code == 401


def test_box_event_missing_field_gives_422(client, test_borger_id):
    """Hvis vi mangler obligatoriske felter, skal APIFlask give 422."""
    token = _get_token(client, user_id=1)
    headers = {"Authorization": f"Bearer {token}"}

    # Mangler borger_id
    payload = {"box_open": True}
    response = client.post("/box-event", json=payload, headers=headers)
    assert response.status_code == 422


def test_box_event_invalid_borger_gives_400(client):
    """
    Hvis borger_id ikke findes i DB,
    forventer vi en 400-fejl (ForeignKeyViolation håndteres).
    """
    token = _get_token(client, user_id=1)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {"borger_id": 999999, "box_open": True}
    response = client.post("/box-event", json=payload, headers=headers)
    assert response.status_code == 400


def test_box_event_creates_row_in_db(client, test_borger_id):
    """Med gyldig token skal /box-event indsætte række i databasen."""
    token = _get_token(client, user_id=1)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"borger_id": test_borger_id, "box_open": True}

    response = client.post("/box-event", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "ok"

    # Tjek i databasen at rækken findes
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT box_open
                    FROM box_events
                    WHERE borger_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1;
                    """,
                    (test_borger_id,),
                )
                row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] is True


def test_pulse_event_creates_row(client, test_borger_id):
    """Test /pulse-event rute."""
    token = _get_token(client, user_id=1)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"borger_id": test_borger_id, "bpm": 72}

    response = client.post("/pulse-event", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.get_json()["status"] == "ok"

    # Tjek i DB
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT bpm
                    FROM pulse_events
                    WHERE borger_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1;
                    """,
                    (test_borger_id,),
                )
                row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == 72


def test_vibration_event_creates_row(client, test_borger_id):
    """Test /vibration-event rute."""
    token = _get_token(client, user_id=2)  # armbånd
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"borger_id": test_borger_id, "signaled": True}

    response = client.post("/vibration-event", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.get_json()["status"] == "ok"

    # Tjek i DB
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT signaled
                    FROM vibration_events
                    WHERE borger_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1;
                    """,
                    (test_borger_id,),
                )
                row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] is True


def test_dashboard_returns_html(client):
    """Test at /dashboard svarer med HTML (status 200)."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Medicinboks" in html or "Medibox" in html


# ---------- BORGER CRUD TESTS ----------

def test_create_borger_valid(client):
    """Opretter en borger via /borger med gyldige felter."""
    payload = {
        "navn": "Bente Beboer",
        "telefon": "12345678",
        "adresse": "Plejehjemsvej 10",
        "vaerelse": "12A",
    }
    response = client.post("/borger", json=payload)
    assert response.status_code == 201
    data = response.get_json()
    assert "id" in data
    assert data["navn"] == "Bente Beboer"


def test_create_borger_invalid_phone(client):
    """Ugyldigt telefonnummer skal give 400."""
    payload = {
        "navn": "Test Telefon",
        "telefon": "12-34-56",  # forkert format
    }
    response = client.post("/borger", json=payload)
    assert response.status_code == 400


def test_create_borger_invalid_room(client):
    """Ugyldigt værelseformat skal give 400."""
    payload = {
        "navn": "Test Værelse",
        "vaerelse": "123456",  # for langt (mere end 5 tegn)
    }
    response = client.post("/borger", json=payload)
    assert response.status_code == 400


def test_list_borgere_includes_created(client):
    """Efter oprettelse af en borger skal den fremgå af /borger-listen."""
    payload = {"navn": "List Test", "telefon": "87654321"}
    r = client.post("/borger", json=payload)
    assert r.status_code == 201
    created_id = r.get_json()["id"]

    response = client.get("/borger")
    assert response.status_code == 200
    data = response.get_json()
    assert "borgere" in data

    ids = [b["id"] for b in data["borgere"]]
    assert created_id in ids


def test_update_borger_works(client):
    """Test at PUT /borger/<id> opdaterer en borger."""
    # Opret først
    create_payload = {"navn": "Original Navn"}
    r = client.post("/borger", json=create_payload)
    assert r.status_code == 201
    bid = r.get_json()["id"]

    # Opdater
    update_payload = {"navn": "Opdateret Navn", "telefon": "12345678"}
    r2 = client.put(f"/borger/{bid}", json=update_payload)
    assert r2.status_code == 200
    assert r2.get_json()["status"] == "updated"

    # Tjek i DB
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT navn, telefon FROM borger WHERE id = %s;",
                    (bid,),
                )
                row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == "Opdateret Navn"
    assert row[1] == "12345678"


def test_delete_borger_works(client):
    """Test at DELETE /borger/<id> sletter en borger."""
    # Opret først
    r = client.post("/borger", json={"navn": "Slet Mig"})
    assert r.status_code == 201
    bid = r.get_json()["id"]

    # Slet
    r2 = client.delete(f"/borger/{bid}")
    assert r2.status_code == 200
    assert r2.get_json()["status"] == "deleted"

    # Tjek i DB at den er væk
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM borger WHERE id = %s;", (bid,))
                row = cur.fetchone()
    finally:
        conn.close()

    assert row is None
