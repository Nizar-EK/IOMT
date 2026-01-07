# app.py
from flask import render_template
from apiflask import APIFlask, Schema, HTTPTokenAuth, abort
from apiflask.fields import Boolean, Integer, String
from authlib.jose import jwt, JoseError
import secrets
from datetime import datetime
import psycopg2
import psycopg2.extras
from psycopg2.errors import ForeignKeyViolation
import re

# ---------- SETUP ----------
app = APIFlask(__name__)
auth = HTTPTokenAuth(scheme="Bearer")
app.config["SECRET_KEY"] = secrets.token_bytes(32)


def get_db_connection():
    """
    Opretter forbindelse til PostgreSQL.
    """
    conn = psycopg2.connect(
        host="127.0.0.1",
        port="5432",
        dbname="iomt",
        user="iomt_user",
        password="1234",
    )
    return conn


# ---------- REGEX (programmering: Regex) ----------
PHONE_REGEX = re.compile(r"^(?:\+45\s?)?\d{8}$")
ROOM_REGEX = re.compile(r"^[A-Za-z0-9]{1,5}$")


# ---------- SIMPLE "BRUGERE" / ENHEDER TIL TOKENS ----------
class User:
    def __init__(self, id: int, secret: str):
        self.id = id
        self.secret = secret

    def get_token(self) -> str:
        header = {"alg": "HS256"}
        payload = {"id": self.id}
        # jwt.encode returnerer bytes → dekoder til str
        return jwt.encode(header, payload, app.config["SECRET_KEY"]).decode()


class TokenOut(Schema):
    token = String()


# 1 = ESP32 i medicinboks (LDR + puls)
# 2 = ESP32 i armbånd (vibrator)
users = [
    User(1, "Medicinboks – borger 1"),
    User(2, "Armbånd – borger 1"),
]


def get_user_by_id(id: int) -> User | None:
    matches = [u for u in users if u.id == id]
    return matches[0] if matches else None


@auth.verify_token
def verify_token(token: str) -> User | None:
    """Validerer Bearer-token og returnerer User-objektet eller None."""
    try:
        data = jwt.decode(
            token.encode("ascii"),
            app.config["SECRET_KEY"],
        )
        uid = data["id"]
        user = get_user_by_id(uid)
    except (JoseError, KeyError, IndexError):
        return None
    return user


# ---------- SCHEMAS TIL API ----------
class BorgerIn(Schema):
    #kun navn er påkrævet
    navn = String(required=True)
    telefon = String(required=False)
    adresse = String(required=False)
    vaerelse = String(required=False)


class BoxEventIn(Schema):
    borger_id = Integer(required=True)
    box_open = Boolean(required=True)   # True = åben, False = lukket


class PulseEventIn(Schema):
    borger_id = Integer(required=True)
    bpm = Integer(required=True)        # puls i slag/minut


class VibrationEventIn(Schema):
    borger_id = Integer(required=True)
    signaled = Boolean(required=True)   # True = armbånd har vibreret


# ---------- ROUTES: GENERELT ----------
@app.get("/")
def index():
    return {"message": "Medibox API kører – se /dashboard for oversigt"}


@app.get("/dashboard")
def dashboard():
    """Vis simpel oversigt som tabeller til medarbejdere fra PostgreSQL"""

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                # Medicinboks events
                cur.execute(
                    """
                    SELECT b.navn,
                           e.box_open,
                           e.created_at
                    FROM box_events e
                    JOIN borger b ON e.borger_id = b.id
                    ORDER BY e.created_at DESC
                    LIMIT 10;
                    """
                )
                box_events = cur.fetchall()

                # Puls events
                cur.execute(
                    """
                    SELECT b.navn,
                           e.bpm,
                           e.created_at
                    FROM pulse_events e
                    JOIN borger b ON e.borger_id = b.id
                    ORDER BY e.created_at DESC
                    LIMIT 10;
                    """
                )
                pulse_events = cur.fetchall()

                # Vibration events
                cur.execute(
                    """
                    SELECT b.navn,
                           e.signaled,
                           e.created_at
                    FROM vibration_events e
                    JOIN borger b ON e.borger_id = b.id
                    ORDER BY e.created_at DESC
                    LIMIT 10;
                    """
                )
                vibration_events = cur.fetchall()
    finally:
        conn.close()

    return render_template(
        "dashboard.html",
        box_events=box_events,
        pulse_events=pulse_events,
        vibration_events=vibration_events,
    )


@app.post("/token/<int:id>")
@app.output(TokenOut)
def get_token(id: int):
    """Returnér JWT-token til en enhed (ESP32)."""
    user = get_user_by_id(id)
    if user is None:
        abort(404)
    return {"token": user.get_token()}


# ---------- ROUTES: BORGER CRUD (Programmering: CRUD + Regex) ----------

@app.post("/borger")
@app.input(BorgerIn)
def create_borger(json_data):
    """
    Opretter en ny borger.
    Regex bruges til at validere telefon og værelse, hvis de er angivet.
    """
    navn = json_data["navn"].strip()
    telefon = (json_data.get("telefon") or "").strip()
    adresse = (json_data.get("adresse") or "").strip()
    vaerelse = (json_data.get("vaerelse") or "").strip()

    # Telefon-validering (kun hvis feltet er udfyldt)
    if telefon and not PHONE_REGEX.match(telefon):
        abort(400, "Ugyldigt telefonnummer (skal være 8 cifre, evt. med +45).")

    # Værelse-validering (kun hvis udfyldt)
    if vaerelse and not ROOM_REGEX.match(vaerelse):
        abort(400, "Ugyldigt værelseformat (1-5 tegn, kun bogstaver og tal).")

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
                    (navn, telefon or None, adresse or None, vaerelse or None),
                )
                new_id = cur.fetchone()[0]
    finally:
        conn.close()

    return {"id": new_id, "navn": navn}, 201


@app.get("/borger")
def list_borgere():
    """
    Returnerer liste af borgere.
    """
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, navn, telefon, adresse, vaerelse
                    FROM borger
                    ORDER BY id;
                    """
                )
                rows = cur.fetchall()
    finally:
        conn.close()

    return {"borgere": [dict(r) for r in rows]}, 200


@app.put("/borger/<int:borger_id>")
@app.input(BorgerIn)
def update_borger(borger_id: int, json_data):
    """
    Opdaterer en eksisterende borger.
    Vi kræver stadig navn (schema), men de andre er valgfrie.
    """
    navn = json_data["navn"].strip()
    telefon = (json_data.get("telefon") or "").strip()
    adresse = (json_data.get("adresse") or "").strip()
    vaerelse = (json_data.get("vaerelse") or "").strip()

    if telefon and not PHONE_REGEX.match(telefon):
        abort(400, "Ugyldigt telefonnummer (skal være 8 cifre, evt. med +45).")

    if vaerelse and not ROOM_REGEX.match(vaerelse):
        abort(400, "Ugyldigt værelseformat (1-5 tegn, kun bogstaver og tal).")

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE borger
                    SET navn = %s,
                        telefon = %s,
                        adresse = %s,
                        vaerelse = %s
                    WHERE id = %s
                    RETURNING id;
                    """,
                    (navn, telefon or None, adresse or None, vaerelse or None, borger_id),
                )
                row = cur.fetchone()
                if row is None:
                    abort(404, "Borger ikke fundet.")
    finally:
        conn.close()

    return {"status": "updated", "id": borger_id}, 200


@app.delete("/borger/<int:borger_id>")
def delete_borger(borger_id: int):
    """
    Sletter en borger. Relaterede events slettes automatisk pga. ON DELETE CASCADE.
    """
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM borger WHERE id = %s RETURNING id;",
                    (borger_id,),
                )
                row = cur.fetchone()
                if row is None:
                    abort(404, "Borger ikke fundet.")
    finally:
        conn.close()

    return {"status": "deleted", "id": borger_id}, 200


# ---------- ROUTES: EVENTS (ESP32 → API → DB) ----------

@app.post("/box-event")
@auth.login_required
@app.input(BoxEventIn)
def box_event(json_data):
    """Kaldes af ESP32 i medicinboks (åben/lukket boks)."""
    borger_id = json_data["borger_id"]
    box_open = json_data["box_open"]

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO box_events (borger_id, box_open)
                        VALUES (%s, %s);
                        """,
                        (borger_id, box_open),
                    )
                except ForeignKeyViolation:
                    abort(400, "Ukendt borger_id.")
    finally:
        conn.close()

    return {"status": "ok"}, 201


@app.post("/pulse-event")
@auth.login_required
@app.input(PulseEventIn)
def pulse_event(json_data):
    """Kaldes af ESP32 i medicinboks (pulssensor)."""
    borger_id = json_data["borger_id"]
    bpm = json_data["bpm"]

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO pulse_events (borger_id, bpm)
                        VALUES (%s, %s);
                        """,
                        (borger_id, bpm),
                    )
                except ForeignKeyViolation:
                    abort(400, "Ukendt borger_id.")
    finally:
        conn.close()

    return {"status": "ok"}, 201


@app.post("/vibration-event")
@auth.login_required
@app.input(VibrationEventIn)
def vibration_event(json_data):
    """Kaldes af ESP32 i armbåndet, når det vibrerer."""
    borger_id = json_data["borger_id"]
    signaled = json_data["signaled"]

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO vibration_events (borger_id, signaled)
                        VALUES (%s, %s);
                        """,
                        (borger_id, signaled),
                    )
                except ForeignKeyViolation:
                    abort(400, "Ukendt borger_id.")
    finally:
        conn.close()

    return {"status": "ok"}, 201



@app.get("/box-events")
def get_box_events():
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT b.navn,
                           e.box_open,
                           e.created_at
                    FROM box_events e
                    JOIN borger b ON e.borger_id = b.id
                    ORDER BY e.created_at DESC;
                    """
                )
                rows = cur.fetchall()
    finally:
        conn.close()
    return {"events": [dict(r) for r in rows]}


@app.get("/pulse-events")
def get_pulse_events():
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT b.navn,
                           e.bpm,
                           e.created_at
                    FROM pulse_events e
                    JOIN borger b ON e.borger_id = b.id
                    ORDER BY e.created_at DESC;
                    """
                )
                rows = cur.fetchall()
    finally:
        conn.close()
    return {"events": [dict(r) for r in rows]}


@app.get("/vibration-events")
def get_vibration_events():
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT b.navn,
                           e.signaled,
                           e.created_at
                    FROM vibration_events e
                    JOIN borger b ON e.borger_id = b.id
                    ORDER BY e.created_at DESC;
                    """
                )
                rows = cur.fetchall()
    finally:
        conn.close()
    return {"events": [dict(r) for r in rows]}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

