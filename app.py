# app.py
from flask import render_template
from apiflask import APIFlask, Schema, HTTPTokenAuth, abort
from apiflask.fields import Boolean, Integer, String
from authlib.jose import jwt, JoseError
import secrets
from datetime import datetime

# ---------- SETUP ----------
app = APIFlask(__name__)
auth = HTTPTokenAuth(scheme="Bearer")
app.config["SECRET_KEY"] = secrets.token_bytes(32)


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


# ---------- IN-MEMORY DATA (senere PostgreSQL) ----------
BOX_EVENTS: list[dict] = []         # åben/lukket boks
PULSE_EVENTS: list[dict] = []       # puls målinger
VIBRATION_EVENTS: list[dict] = []   # armbånd vibreret


# ---------- SCHEMAS TIL API ----------
class BoxEventIn(Schema):
    box_open = Boolean(required=True)   # True = åben, False = lukket
    adc_value = Integer()               # fx rå LDR-værdi (valgfri)


class PulseEventIn(Schema):
    bpm = Integer(required=True)        # puls i slag/minut


class VibrationEventIn(Schema):
    strength = Integer()                # valgfri: hvor kraftig vibration (0-100)


# ---------- ROUTES ----------

@app.get("/")
def index():
    # simpelt svar, plus hint om dashboard
    return {"message": "Medibox API kører – se /dashboard for oversigt"}


@app.get("/dashboard")
def dashboard():
    """Vis simpel oversigt som tabeller til medarbejdere."""
    return render_template(
        "dashboard.html",
        box_events=BOX_EVENTS,
        pulse_events=PULSE_EVENTS,
        vibration_events=VIBRATION_EVENTS,
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
def box_event(data):
    """Kaldes af ESP32 i medicinboks (åben/lukket boks)."""
    event = {
        "device": auth.current_user().secret,
        "box_open": data["box_open"],
        "adc_value": data.get("adc_value"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    BOX_EVENTS.append(event)
    return {"status": "ok"}, 201


@app.post("/pulse-event")
@auth.login_required
@app.input(PulseEventIn)
def pulse_event(data):
    """Kaldes af ESP32 i medicinboks (pulssensor)."""
    event = {
        "device": auth.current_user().secret,
        "bpm": data["bpm"],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    PULSE_EVENTS.append(event)
    return {"status": "ok"}, 201


@app.post("/vibration-event")
@auth.login_required
@app.input(VibrationEventIn)
def vibration_event(data):
    """Kaldes af ESP32 i armbåndet, når det vibrerer."""
    event = {
        "device": auth.current_user().secret,
        "strength": data.get("strength"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    VIBRATION_EVENTS.append(event)
    return {"status": "ok"}, 201


# (valgfrit) JSON-endpoints til jer selv / debugging
@app.get("/box-events")
def get_box_events():
    return {"events": BOX_EVENTS}


@app.get("/pulse-events")
def get_pulse_events():
    return {"events": PULSE_EVENTS}


@app.get("/vibration-events")
def get_vibration_events():
    return {"events": VIBRATION_EVENTS}


if __name__ == "__main__":
    app.run(debug=True)
