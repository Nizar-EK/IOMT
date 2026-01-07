import network
import time
import urequests as requests
import json
from machine import Pin

# ----------------- WIFI -----------------
WIFI_SSID = "8awifi"
WIFI_PASS = "Gruppe8a!"

# ----------------- API -----------------
API_BASE = "http://192.168.0.52:5000"
DEVICE_ID = 2
BORGER_ID = 1

# ----------------- VIBRATOR -----------------
VIBRATION_PIN = 12
vibrator = Pin(VIBRATION_PIN, Pin.OUT)
vibrator.off()

VIBRATION_TIME = 5  # én vibration i 5 sek

# ----------------- TIDSPUNKT -----------------
TARGET_HOUR = 16
TARGET_MINUTE = 37

TOKEN = None


def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Forbinder til WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASS)
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1

    if wlan.isconnected():
        print("WiFi OK:", wlan.ifconfig())
        return True
    print("WiFi FEJL")
    return False


def get_token():
    global TOKEN
    try:
        url = f"{API_BASE}/token/{DEVICE_ID}"
        r = requests.post(url)
        data = r.json()
        r.close()
        TOKEN = data["token"]
        print("Token hentet")
        return True
    except Exception as e:
        print("Token FEJL:", e)
        TOKEN = None
        return False


def post_vibration_event():
    global TOKEN
    if TOKEN is None:
        print("Ingen token - prøver at hente igen...")
        if not get_token():
            return False

    url = f"{API_BASE}/vibration-event"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + TOKEN
    }
    payload = {"borger_id": BORGER_ID, "signaled": True}

    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload))
        status = r.status_code
        text = r.text
        r.close()
        print("vibration-event:", status, text)

        if status in (401, 403):
            TOKEN = None
            print("Token afvist - henter nyt token og prøver igen...")
            if get_token():
                r2 = requests.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + TOKEN
                        },
                    data=json.dumps(payload)
                )
                print("vibration-event retry:", r2.status_code, r2.text)
                r2.close()
        return True
    except Exception as e:
        print("POST FEJL:", e)
        return False


def vibrate_once():
    print("Vibration START")
    vibrator.on()
    time.sleep(VIBRATION_TIME)
    vibrator.off()
    print("Vibration STOP")


def should_vibrate_now():
    now = time.localtime()
    # now[3]=hour, now[4]=minute
    return (now[3] == TARGET_HOUR and now[4] == TARGET_MINUTE)


# ----------------- START -----------------
print("Armbånd-ESP startet")

wifi_connect()
get_token()

# Print tiden én gang ved opstart (til test/indstilling)
print("ESP starttid (localtime):", time.localtime())
print("Tester vibration kl:", TARGET_HOUR, ":", TARGET_MINUTE)

last_minute_run = None

while True:

    if should_vibrate_now():
        current_minute = time.localtime()[4]
        
        # Kør kun én gang pr. minut
        if last_minute_run != current_minute:
            last_minute_run = current_minute

            vibrate_once()
            post_vibration_event()

            # undgå at trigge flere gange samme minut
            time.sleep(60)

    time.sleep(2)
