import requests

BASE = "http://127.0.0.1:5000"

# ---------- 1. HENT TOKEN ----------
r = requests.post(f"{BASE}/token/1")
token = r.json()["token"]
bearer = f"Bearer {token}"
print("Token modtaget:", bearer)


headers = {
    "Authorization": bearer,
    "Content-Type": "application/json"
}

# ---------- 2. SEND BOX EVENT ----------
box_data = {
    "borger_id": 1,
    "box_open": True
}

r = requests.post(f"{BASE}/box-event", json=box_data, headers=headers)
print("Box event status:", r.status_code, r.text)


# ---------- 3. SEND PULSE EVENT ----------
pulse_data = {
    "borger_id": 1,
    "bpm": 78
}

r = requests.post(f"{BASE}/pulse-event", json=pulse_data, headers=headers)
print("Pulse event status:", r.status_code, r.text)


# ---------- 4. SEND VIBRATION EVENT ----------
vib_data = {
    "borger_id": 1,
    "signaled": True
}

r = requests.post(f"{BASE}/vibration-event", json=vib_data, headers=headers)
print("Vibration event status:", r.status_code, r.text)
