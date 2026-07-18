import os
import json
import time
import random
import smtplib
from email.message import EmailMessage
from urllib.parse import quote_plus
import requests

# ---------------- CONFIG ----------------
API_KEY = os.environ["TANKERKOENIG_API_KEY"]

SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
EMAIL_TO = os.environ["EMAIL_TO"]

# WATCH DIESEL
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

# Helps pick the correct JET if there are multiple nearby
STREET_HINTS = [s.strip().lower() for s in os.environ.get("STREET_HINTS", "elisabeth,selbert").split(",") if s.strip()]

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

def list_nearby_all():
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
    if not data.get("ok"):
        raise RuntimeError(f"Tankerkönig list.php error: {data}")
    return data.get("stations", [])

def is_jet_station(station):
    name = (station.get("name") or "").lower()
    brand = (station.get("brand") or "").lower()
    return "jet" in name or "jet" in brand

def pick_jet_station(stations):
    candidates = []
    for s in stations:
        name = (s.get("name") or "").lower()
        brand = (s.get("brand") or "").lower()
        street = (s.get("street") or "").lower()

        if "jet" in name or "jet" in brand:
            score = 0
            for h in STREET_HINTS:
                if h and h in street:
                    score += 10
            dist = float(s.get("dist") or 999)
            candidates.append((score, -dist, s))

    if not candidates:
        raise RuntimeError("No JET station found in radius. Increase RADIUS_KM.")
    candidates.sort(reverse=True)
    return candidates[0][2]

def get_prices(station_id):
    url = "https://creativecommons.tankerkoenig.de/json/prices.php"
    params = {
        "ids": station_id,
        "apikey": API_KEY
    }
    data = tk_get(url, params)
    if not data.get("ok"):
        raise RuntimeError(f"Tankerkönig prices.php error: {data}")
    return data["prices"].get(station_id, {})

# ---------------- HELPERS ----------------
def fmt_price(x):
    return "n/a" if x is None else f"{float(x):.3f} €"

def maps_link_from_station(meta: dict):
    lat = meta.get("lat")
    lng = meta.get("lng")
    if lat is not None and lng is not None:
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"

    street = meta.get("street") or ""
    hn = meta.get("houseNumber") or ""
    pc = meta.get("postCode") or ""
    place = meta.get("place") or ""
    q = f"{street} {hn}, {pc} {place}".strip()
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(q)}"

def cheapest_summary(stations):
    def best_for(fuel_key):
        best = None
        for s in stations:
            p = s.get(fuel_key)
            if p is None:
                continue
            try:
                p = float(p)
            except Exception:
                continue
            dist = float(s.get("dist") or 999)
            if best is None or p < best["price"] or (p == best["price"] and dist < best["dist"]):
                best = {
                    "price": p,
                    "dist": dist,
                    "name": s.get("name") or s.get("brand") or "Station",
                    "meta": s
                }
        return best

    return {
        "e5": best_for("e5"),
        "e10": best_for("e10"),
        "diesel": best_for("diesel"),
    }

def cheapest_section(stations):
    best = cheapest_summary(stations)

    lines = ["\nNearby cheapest (within radius):"]
    for key, label in [("e5", "E5"), ("e10", "E10"), ("diesel", "Diesel")]:
        b = best.get(key)
        if not b:
            lines.append(f"- {label}: n/a")
            continue
        meta = b["meta"]
        link = maps_link_from_station(meta)
        street = (meta.get("street") or "")
        hn = (meta.get("houseNumber") or "")
        place = (meta.get("place") or "")
        lines.append(
            f"- {label}: {b['price']:.3f} € @ {b['name']} ({b['dist']:.2f} km) — {street} {hn}, {place}\n  Maps: {link}"
        )

    return "\n".join(lines)

# ---------------- MAIN ----------------
def main():
    time.sleep(random.randint(1, 5))

    state = load_state()

    # Resolve JET station once (cache in state)
    station_id = state.get("station_id")
    station_meta = state.get("station_meta")

    if not station_id:
        stations = list_nearby_all()
        jet = pick_jet_station(stations)
        station_id = jet["id"]
        station_meta = jet

        state["station_id"] = station_id
        state["station_meta"] = station_meta
        save_state(state)

        send_email(
            "Fuel watcher configured (JET)",
            "Monitoring:\n"
            f"{jet.get('name')}\n"
            f"{jet.get('street')} {jet.get('houseNumber', '')}\n"
            f"{jet.get('postCode', '')} {jet.get('place', '')}\n"
            f"Maps: {maps_link_from_station(jet)}\n\n"
            f"Watch fuel: {FUEL.upper()}\n"
            f"LOW: {LOW_THRESHOLD:.3f} € | HIGH: {HIGH_THRESHOLD:.3f} €\n"
            f"Radius: {RADIUS_KM:.1f} km"
        )

    prices = get_prices(station_id)

    diesel_raw = prices.get("diesel")
    if diesel_raw is None:
        return

    diesel_price = float(diesel_raw)

    price_e5 = prices.get("e5")
    price_e10 = prices.get("e10")
    price_diesel = prices.get("diesel")

    fuel_info = (
    "\nCurrent prices at JET:\n"
    f"Diesel: {fmt_price(price_diesel)}\n"
    f"E5: {fmt_price(price_e5)}\n"
    f"E10: {fmt_price(price_e10)}\n"
    f"Maps: {maps_link_from_station(station_meta)}\n"
)

    last = state.get("last_diesel")
    if last is not None:
        last = float(last)

    changed = (last is not None and diesel_price != last)

    label = f"{station_meta.get('name', 'JET')} {station_meta.get('place', '')}"

    def with_cheapest(body: str) -> str:
        stations = list_nearby_all()
        return body + "\n" + cheapest_section(stations)

    # ---------------- ALERTS ----------------
    if diesel_price <= LOW_THRESHOLD:
        body = (
            f"🟢 RUN AND TANK\n\n"
            f"{label}\n"
            f"Diesel is now {diesel_price:.3f} € (<= {LOW_THRESHOLD:.3f} €)\n\n"
            + fuel_info
        )
        send_email(
            f"🟢 RUN AND TANK ({diesel_price:.3f}€)",
            with_cheapest(body)
        )

    elif diesel_price >= HIGH_THRESHOLD:
        body = (
            f"🔴 HIGH DIESEL PRICE\n\n"
            f"{label}\n"
            f"Diesel is now {diesel_price:.3f} € (>= {HIGH_THRESHOLD:.3f} €)\n\n"
            + fuel_info
        )
        send_email(
            f"🔴 HIGH DIESEL PRICE ({diesel_price:.3f}€)",
            with_cheapest(body)
        )

    elif EMAIL_ON_ANY_CHANGE and changed:
        body = (
            f"⛽ PRICE CHANGED\n\n"
            f"{label}\n"
            f"Diesel changed: {last:.3f} € → {diesel_price:.3f} €\n"
            f"LOW: {LOW_THRESHOLD:.3f} € | HIGH: {HIGH_THRESHOLD:.3f} €\n\n"
            + fuel_info
        )
        send_email(
            f"⛽ Changed: {label} Diesel",
            with_cheapest(body)
        )

    state["last_diesel"] = diesel_price
    save_state(state)

if __name__ == "__main__":
    main()
