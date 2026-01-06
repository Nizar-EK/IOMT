import network
import urequests as requests
import uasyncio as asyncio
import json
import time
from machine import ADC, Pin

# --------- KONFIGURATION ---------
WIFI_SSID = "8awifi"
WIFI_PASS = "Gruppe8a!"

API_BASE = "http://192.168.0.52:5000"
DEVICE_USER_ID = 1
BORGER_ID = 1

# LDR (medicinboks)
LDR_PIN = 34
LDR_OPEN_THRESHOLD = 2200
LDR_CLOSE_THRESHOLD = 1800
LDR_STABLE_COUNT = 3

# Pulssensor
PULSE_PIN = 32


# Beat-detektion
PEAK_THRESHOLD = 2200             # 1900 gav ofte støj-beats
REFRACTORY_MS = 350

# Validitetsregler
MIN_VALID_BPM = 40
MAX_VALID_BPM = 180
MIN_BEATS_FOR_VALID = 6
MAX_IBI_JITTER = 0.35

token = None
box_open_state = None  # True = åben, False = lukket


# --------- WIFI + TOKEN ---------
def connect_wifi():
    print("Forbinder til WiFi...")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        while not wlan.isconnected():
            time.sleep(0.5)
            print(".", end="")
    print("\nWiFi forbundet:", wlan.ifconfig())


def get_token():
    global token
    url = f"{API_BASE}/token/{DEVICE_USER_ID}"
    print("Henter token fra:", url)

    r = requests.post(url)
    print("Status fra /token:", r.status_code)

    try:
        raw = r.text
    except AttributeError:
        raw = r.content.decode()

    print("Rå svar:", raw)

    if r.status_code != 200:
        r.close()
        raise Exception("Kunne ikke hente token")

    data = json.loads(raw)
    r.close()

    token = data["token"]
    print("Modtog token:", token)


def auth_headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def post_json(path, payload):
    try:
        r = requests.post(
            f"{API_BASE}{path}",
            headers=auth_headers(),
            data=json.dumps(payload),
        )
        try:
            body = r.text
        except AttributeError:
            body = r.content.decode()
        print(path, "->", r.status_code, body)
        r.close()
    except Exception as e:
        print("Fejl ved POST", path, ":", e)


# --------- ADC HJÆLP ---------
def read_adc_avg(adc, samples=10, delay_ms=5):
    total = 0
    for _ in range(samples):
        total += adc.read()
        time.sleep_ms(delay_ms)
    return total // samples





# --------- TASK: BOKS ---------
async def task_box():
    global box_open_state

    adc_ldr = ADC(Pin(LDR_PIN))
    adc_ldr.atten(ADC.ATTN_11DB)

    v0 = read_adc_avg(adc_ldr, samples=12, delay_ms=5)
    if v0 >= LDR_OPEN_THRESHOLD:
        box_open_state = True
    elif v0 <= LDR_CLOSE_THRESHOLD:
        box_open_state = False
    else:
        box_open_state = False

    print("Initial boks-tilstand:", "ÅBEN" if box_open_state else "LUKKET", "ADC:", v0)
    post_json("/box-event", {"borger_id": BORGER_ID, "box_open": box_open_state})

    stable_counter = 0
    candidate_state = box_open_state

    while True:
        v = read_adc_avg(adc_ldr, samples=10, delay_ms=5)

        if box_open_state is False and v >= LDR_OPEN_THRESHOLD:
            candidate_state = True
        elif box_open_state is True and v <= LDR_CLOSE_THRESHOLD:
            candidate_state = False
        else:
            candidate_state = box_open_state

        if candidate_state != box_open_state:
            stable_counter += 1
            if stable_counter >= LDR_STABLE_COUNT:
                box_open_state = candidate_state
                stable_counter = 0

                print("Boks-tilstand ændret:", "ÅBEN" if box_open_state else "LUKKET", "ADC:", v)
                post_json("/box-event", {"borger_id": BORGER_ID, "box_open": box_open_state})
        else:
            stable_counter = 0

        await asyncio.sleep_ms(200)


# --------- TASK: PULS ---------
async def task_pulse():
    adc_pulse = ADC(Pin(PULSE_PIN))
    adc_pulse.atten(ADC.ATTN_11DB)

    while True:
        print("Venter på at boksen åbnes for at måle puls...")
        while box_open_state is not True:
            await asyncio.sleep_ms(100)

        print("Boks åben -> forsøger pulsmåling")

        sent_valid = False

        # Reset målevariabler for åbning
        beats = 0
        beat_times = []
        last_above = False
        last_beat_ms = 0

        while True:
            # Stop hvis boksen lukkes
            if box_open_state is False:
                print("Boks lukket -> stopper pulsmåling.")
                break

            # Hvis vi allerede sendte en valid måling -> vent på lukning
            if sent_valid:
                await asyncio.sleep_ms(200)
                continue

            v = adc_pulse.read()
            now = time.ticks_ms()

            # print kun engang imellem
            if (now % 1000) < 20:
                print("PULSE raw:", v)
                
            above = v > PEAK_THRESHOLD

            # Rising edge + refractory
            if above and not last_above:
                if (last_beat_ms == 0) or (time.ticks_diff(now, last_beat_ms) >= REFRACTORY_MS):
                    beats += 1
                    beat_times.append(now)
                    last_beat_ms = now

                    # Når vi har nok beats -> beregn BPM
                    if beats >= MIN_BEATS_FOR_VALID:
                        ibis = []
                        for i in range(1, len(beat_times)):
                            ibis.append(time.ticks_diff(beat_times[i], beat_times[i - 1]))

                        avg_ibi = sum(ibis) / len(ibis)
                        bpm = int(60000 / avg_ibi)

                        # Validitetscheck
                        if MIN_VALID_BPM <= bpm <= MAX_VALID_BPM:
                            print("VALID BPM:", bpm, "-> sender til API")
                            post_json("/pulse-event", {"borger_id": BORGER_ID, "bpm": int(bpm)})
                            sent_valid = True
                            print("Valid puls sendt -> venter på lukning.")
                        else:
                            # Hvis urealistisk BPM -> reset og prøv igen
                            print("Ugyldig BPM:", bpm, "-> reset måling")
                            beats = 0
                            beat_times = []
                            last_beat_ms = 0

            last_above = above
            await asyncio.sleep_ms(20)



# --------- MAIN ---------
async def main():
    print("Starter main()...")
    connect_wifi()
    print("WiFi OK, henter token...")
    get_token()
    print("Token OK, starter tasks...")

    await asyncio.gather(
        task_box(),
        task_pulse(),
    )

asyncio.run(main())
