import os
import json
import time
import random
import smtplib
from email.message import EmailMessage
import requests

# ---------------- CONFIG ----------------
API_KEY = os.environ["TANKERKOENIG_API_KEY"]

SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
EMAIL_TO = os.environ["EMAIL_TO"]

FUEL = "diesel"

LOW_THRESHOLD = float(os.environ.get("LOW_THRESHOLD", "1.92"))
HIGH_THRESHOLD = float(os.environ.get("HIGH_THRESHOLD", "1.959"))

EMAIL_ON_ANY_CHANGE = os.environ.get(
    "EMAIL_ON_ANY_CHANGE",
    "true"
).lower() == "true"

LAT = float(os.environ.get("LAT", "50.0173"))
LNG = float(os.environ.get("LNG", "8.7870"))
RADIUS_KM = float(os.environ.get("RADIUS_KM", "5"))

STATE_FILE = "state.json"

# ---------------- EMAIL ----------------
def send_email(subject, body):
    msg = EmailMessage()

    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject

    msg.set_content(body)

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)

# ---------------- STATE ----------------
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

# ---------------- API ----------------
def tk_get(url, params):
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()

def is_jet_station(station):
    name = (station.get("name") or "").lower()
    brand = (station.get("brand") or "").lower()

    return "jet" in name or "jet" in brand

def list_nearby_jet():
    url = "https://creativecommons.tankerkoenig.de/json/list.php"

    params = {
        "lat": LAT,
        "lng": LNG,
        "rad": RADIUS_KM,
        "sort": "dist",
        "type": "all",
        "apikey": API_KEY
    }

    data = tk_get(url, params)

    stations = data.get("stations", [])

    return [s for s in stations if is_jet_station(s)]

def get_prices(station_id):
    url = "https://creativecommons.tankerkoenig.de/json/prices.php"

    params = {
        "ids": station_id,
        "apikey": API_KEY
    }

    data = tk_get(url, params)

    return data["prices"].get(station_id, {})

# ---------------- OUTPUT ----------------
def fuel_summary(prices):
    diesel = prices.get("diesel")
    e5 = prices.get("e5")
    e10 = prices.get("e10")

    return (
        "\nCurrent prices:\n"
        f"Diesel: {diesel}\n"
        f"E5: {e5}\n"
        f"E10: {e10}\n"
    )

# ---------------- MAIN ----------------
def main():

    time.sleep(random.randint(1, 5))

    state = load_state()

    stations = list_nearby_jet()

    if not stations:
        raise RuntimeError("No JET stations found")

    # CLOSEST JET
    jet = min(
        stations,
        key=lambda s: s.get("dist", 999)
    )

    station_id = jet["id"]

    prices = get_prices(station_id)

    diesel_raw = prices.get("diesel")

    if diesel_raw is None:
        return

    diesel_price = float(diesel_raw)

    # ---------------- FORCE TEST EMAIL ----------------
    send_email(
        "✅ PIPELINE TEST EMAIL",
        (
            "Pipeline is working correctly.\n\n"
            f"Current Diesel: {diesel_price:.3f} €\n"
            + fuel_summary(prices)
        )
    )

    last = state.get("last_diesel")

    if last is not None:
        last = float(last)

    changed = (
        last is not None and
        diesel_price != last
    )

    # ---------------- ALERTS ----------------
    if diesel_price <= LOW_THRESHOLD:

        send_email(
            f"🟢 RUN AND TANK ({diesel_price:.3f}€)",
            (
                f"Diesel is CHEAP\n\n"
                f"Diesel: {diesel_price:.3f} €\n"
                + fuel_summary(prices)
            )
        )

    elif diesel_price >= HIGH_THRESHOLD:

        send_email(
            f"🔴 HIGH DIESEL PRICE ({diesel_price:.3f}€)",
            (
                f"Diesel is EXPENSIVE\n\n"
                f"Diesel: {diesel_price:.3f} €\n"
                + fuel_summary(prices)
            )
        )

    elif EMAIL_ON_ANY_CHANGE and changed:

        send_email(
            f"⛽ DIESEL UPDATE {diesel_price:.3f}€",
            (
                f"Diesel changed:\n"
                f"{last:.3f} € → {diesel_price:.3f} €\n"
                + fuel_summary(prices)
            )
        )

    state["last_diesel"] = diesel_price

    save_state(state)

if __name__ == "__main__":
    main()
