# app.py
from flask import render_template
from apiflask import APIFlask, Schema, HTTPTokenAuth, abort
from apiflask.fields import Boolean, Integer, String
from authlib.jose import jwt, JoseError
import secrets
from datetime import datetime
import psycopg2
import psycopg2.extras

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
        dbname="iomt_db",      
        user="postgres",       
        password="1234",  
    )
    return conn


# ---------- SIMPLE "BRUGERE" / ENHEDER TIL TOKENS ----------
class User:
    def __init__(self, id: int, secret: str):
        self.id = id
        # secret kan være en tekst, der beskriver enheden
        self.secret = secret

    def get_token(self) -> str:
        header = {"alg": "HS256"}
        payload = {"id": self.id}
        # jwt.encode returnerer bytes → dekoder til str
        return jwt.encode(header, payload, app.config["SECRET_KEY"]).decode()


class TokenOut(Schema):
    token = String()


# Her opretter vi to enheder:
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
class BoxEventIn(Schema):
    borger_id = Integer(required=True)
    box_open = Boolean(required=True)   # True = åben, False = lukket


class PulseEventIn(Schema):
    borger_id = Integer(required=True)
    bpm = Integer(required=True)        # puls i slag/minut


class VibrationEventIn(Schema):
    borger_id = Integer(required=True)
    signaled = Boolean(required=True)   # True = armbånd har vibreret


# ---------- ROUTES ----------

@app.get("/")
def index():
    # simpelt svar, plus hint om dashboard
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
                    LIMIT 50;
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
                    LIMIT 50;
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
                    LIMIT 50;
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
                cur.execute(
                    """
                    INSERT INTO box_events (borger_id, box_open)
                    VALUES (%s, %s);
                    """,
                    (borger_id, box_open),
                )
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
                cur.execute(
                    """
                    INSERT INTO pulse_events (borger_id, bpm)
                    VALUES (%s, %s);
                    """,
                    (borger_id, bpm),
                )
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
                cur.execute(
                    """
                    INSERT INTO vibration_events (borger_id, signaled)
                    VALUES (%s, %s);
                    """,
                    (borger_id, signaled),
                )
    finally:
        conn.close()

    return {"status": "ok"}, 201


# (valgfrit) JSON-endpoints til jer selv / debugging
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
    app.run(debug=True)
