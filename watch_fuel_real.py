import os, json, time, random
import smtplib
from email.message import EmailMessage
import requests

# ---------------- CONFIG ----------------
API_KEY = os.environ["TANKERKOENIG_API_KEY"]

SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
EMAIL_TO  = os.environ["EMAIL_TO"]

# DIESEL ONLY LOGIC
FUEL = "diesel"

# THRESHOLDS
LOW_THRESHOLD  = float(os.environ.get("LOW_THRESHOLD", "1.92"))
HIGH_THRESHOLD = float(os.environ.get("HIGH_THRESHOLD", "1.959"))

EMAIL_ON_ANY_CHANGE = os.environ.get("EMAIL_ON_ANY_CHANGE", "true").lower() == "true"

LAT = float(os.environ.get("LAT", "50.0173"))
LNG = float(os.environ.get("LNG", "8.7870"))
RADIUS_KM = float(os.environ.get("RADIUS_KM", "5"))

STATE_FILE = "state.json"

# ---------------- EMAIL ----------------
def send_email(subject: str, body: str):
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)

# ---------------- STATE ----------------
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

# ---------------- API ----------------
def tk_get(url, params):
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

# ---------------- JET FILTER ----------------
def is_jet_station(s):
    name = (s.get("name") or "").lower()
    brand = (s.get("brand") or "").lower()
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
        f"Diesel: {diesel if diesel is not None else 'n/a'}\n"
        f"E5: {e5 if e5 is not None else 'n/a'}\n"
        f"E10: {e10 if e10 is not None else 'n/a'}\n"
    )

# ---------------- MAIN ----------------
def main():
    time.sleep(random.randint(1, 10))

    state = load_state()

    stations = list_nearby_jet()

    if not stations:
        raise RuntimeError("No JET stations found in radius")

    # ALWAYS CLOSEST JET
    jet = min(stations, key=lambda s: s.get("dist", 999))

    station_id = state.get("station_id")
    station_meta = state.get("station_meta")

    if not station_id:
        station_id = jet["id"]
        station_meta = jet

        state["station_id"] = station_id
        state["station_meta"] = station_meta

        save_state(state)

        send_email(
            "JET Diesel Watcher Activated",
            f"{jet['name']}\n"
            f"{jet.get('street','')} {jet.get('houseNumber','')}\n\n"
            f"https://www.google.com/maps/search/?api=1&query={jet['lat']},{jet['lng']}"
        )

    prices = get_prices(station_id)

    price_raw = prices.get("diesel")

    if price_raw is None:
        return

    price_now = float(price_raw)

    last = state.get("last_diesel")

    last = float(last) if last is not None else None

    changed = last is not None and price_now != last

    # ---------------- ALERTS ----------------
    if price_now <= LOW_THRESHOLD:

        send_email(
            f"🟢 RUN AND TANK (DIESEL {price_now:.3f}€)",
            f"DIESEL PRICE IS LOW\n\n"
            f"Current Diesel: {price_now:.3f} €\n"
            f"Cheap Threshold: {LOW_THRESHOLD}\n"
            + fuel_summary(prices)
        )

    elif price_now >= HIGH_THRESHOLD:

        send_email(
            f"🔴 WARNING HIGH PRICE (DIESEL {price_now:.3f}€)",
            f"DIESEL PRICE IS HIGH\n\n"
            f"Current Diesel: {price_now:.3f} €\n"
            f"High Threshold: {HIGH_THRESHOLD}\n"
            + fuel_summary(prices)
        )

    elif EMAIL_ON_ANY_CHANGE and changed:

        send_email(
            f"⛽ DIESEL UPDATE {price_now:.3f}€",
            f"Diesel changed:\n"
            f"{last:.3f} € → {price_now:.3f} €\n"
            + fuel_summary(prices)
        )

    # SAVE STATE
    state["last_diesel"] = price_now

    save_state(state)

if __name__ == "__main__":
    main()
