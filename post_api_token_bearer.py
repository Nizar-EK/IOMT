import requests

BASE_URL = "http://127.0.0.1:5000"


def get_token(user_id: int) -> str:
    """
    Henter JWT-token fra /token/<id> endpointet.
    user_id = 1 -> ESP32 i medicinboks (LDR + puls)
    user_id = 2 -> ESP32 i armbånd (vibrator)
    """
    url = f"{BASE_URL}/token/{user_id}"
    r = requests.post(url)
    r.raise_for_status()
    raw_token = r.json()["token"]    
    bearer_token = f"Bearer {raw_token}"
    print(f"Modtog token for user {user_id}: {bearer_token}")
    return bearer_token


def send_box_event(token: str):
    """
    Simulerer, at medicinboksen sender et åben/lukket-event.
    """
    url = f"{BASE_URL}/box-event"
    headers = {
        "Authorization": token,
        "accept": "application/json",
    }
    data = {
        "box_open": True,   
        "adc_value": 1500,  
    }
    r = requests.post(url, json=data, headers=headers)
    print("box-event:", r.status_code, r.text)


def send_pulse_event(token: str):
    """
    Simulerer, at pulssensoren i boksen sender en pulsmåling.
    """
    url = f"{BASE_URL}/pulse-event"
    headers = {
        "Authorization": token,
        "accept": "application/json",
    }
    data = {
        "bpm": 72,   # fiktiv puls
    }
    r = requests.post(url, json=data, headers=headers)
    print("pulse-event:", r.status_code, r.text)


def send_vibration_event(token: str):
    """
    Simulerer, at armbåndet har vibreret (påmindelse sendt).
    """
    url = f"{BASE_URL}/vibration-event"
    headers = {
        "Authorization": token,
        "accept": "application/json",
    }
    data = {
        "strength": 80,   # fiktiv vibrationsstyrke (0–100)
    }
    r = requests.post(url, json=data, headers=headers)
    print("vibration-event:", r.status_code, r.text)


if __name__ == "__main__":
    # Token til medicinboks (user 1)
    box_token = get_token(1)
    send_box_event(box_token)
    send_pulse_event(box_token)

    # Token til armbånd (user 2)
    bracelet_token = get_token(2)
    send_vibration_event(bracelet_token)

    print("Færdig. Tjek /dashboard i browseren.")
