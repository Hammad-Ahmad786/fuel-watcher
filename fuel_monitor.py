import os
import json
import time
import random
import smtplib
from email.message import EmailMessage
from urllib.parse import quote_plus

import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.environ["TANKERKOENIG_API_KEY"]
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
EMAIL_TO = os.environ["EMAIL_TO"]

# Classification thresholds
GOOD_THRESHOLD = float(os.environ.get("GOOD_THRESHOLD", "2.170"))
HIGH_THRESHOLD = float(os.environ.get("HIGH_THRESHOLD", "2.200"))

LAT = float(os.environ.get("LAT", "50.0173"))
LNG = float(os.environ.get("LNG", "8.7870"))
RADIUS_KM = float(os.environ.get("RADIUS_KM", "5"))

STREET_HINTS = [
    value.strip().lower()
    for value in os.environ.get(
        "STREET_HINTS", "elisabeth,selbert"
    ).split(",")
    if value.strip()
]

STATE_FILE = "state.json"
LIST_URL = "https://creativecommons.tankerkoenig.de/json/list.php"

ALLOWED_BRANDS = ("jet", "aral", "shell")


# ============================================================
# EMAIL
# ============================================================

def send_email(subject, body):
    message = EmailMessage()
    message["From"] = SMTP_USER
    message["To"] = EMAIL_TO
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(message)


# ============================================================
# STATE
# ============================================================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)
            return state if isinstance(state, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    temporary_file = STATE_FILE + ".tmp"

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    os.replace(temporary_file, STATE_FILE)


# ============================================================
# TANKERKÖNIG API
# ============================================================

def list_nearby_stations():
    params = {
        "lat": LAT,
        "lng": LNG,
        "rad": RADIUS_KM,
        "sort": "dist",
        "type": "all",
        "apikey": API_KEY,
    }

    response = requests.get(LIST_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(f"Tankerkönig API error: {data}")

    return data.get("stations", [])


# ============================================================
# STATION HELPERS
# ============================================================

def distance(station):
    try:
        return float(station.get("dist") or 999)
    except (TypeError, ValueError):
        return 999


def diesel_price(station):
    try:
        price = float(station.get("diesel"))
        return price if price > 0 else None
    except (TypeError, ValueError):
        return None


def format_price(value):
    try:
        return f"{float(value):.3f} €/L"
    except (TypeError, ValueError):
        return "Unavailable"


def station_name(station):
    name = station.get("name") or station.get("brand") or "Unknown station"
    place = station.get("place") or ""
    return f"{name}, {place}".strip(", ")


def station_address(station):
    street = station.get("street") or ""
    number = station.get("houseNumber") or ""
    postcode = station.get("postCode") or ""
    place = station.get("place") or ""
    return f"{street} {number}, {postcode} {place}".strip(" ,")


def maps_link(station):
    latitude = station.get("lat")
    longitude = station.get("lng")

    if latitude is not None and longitude is not None:
        query = f"{latitude},{longitude}"
    else:
        query = station_address(station)

    return (
        "https://www.google.com/maps/search/?api=1&query="
        + quote_plus(str(query))
    )


def is_jet(station):
    brand = (station.get("brand") or "").strip().lower()
    name = (station.get("name") or "").strip().lower()
    return brand == "jet" or "jet" in name


def is_allowed_station(station):
    brand = (station.get("brand") or "").strip().lower()
    name = (station.get("name") or "").strip().lower()

    return any(
        brand == allowed or allowed in name
        for allowed in ALLOWED_BRANDS
    )


def pick_jet_station(stations, state):
    previous_id = state.get("station_id")

    if previous_id:
        for station in stations:
            if (
                station.get("id") == previous_id
                and is_jet(station)
                and distance(station) <= RADIUS_KM
            ):
                return station

    candidates = []

    for station in stations:
        if not is_jet(station):
            continue

        if distance(station) > RADIUS_KM:
            continue

        street = (station.get("street") or "").lower()
        score = sum(10 for hint in STREET_HINTS if hint in street)

        candidates.append((score, -distance(station), station))

    if not candidates:
        raise RuntimeError(
            "JET reference station not found within 5 km. "
            "Check the coordinates and station data."
        )

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def valid_diesel_stations(stations):
    result = []

    for station in stations:
        if not station.get("id"):
            continue

        if distance(station) > RADIUS_KM:
            continue

        if not is_allowed_station(station):
            continue

        if diesel_price(station) is None:
            continue

        result.append(station)

    return result


# ============================================================
# PRICE CLASSIFICATION
# ============================================================

def classify_station(price, jet_price):
    # High-price rule takes priority.
    if price >= HIGH_THRESHOLD:
        return "🔴 HIGH PRICE"

    # Green requires BOTH conditions:
    # 1. Below €2.17/L
    # 2. Cheaper than JET
    if price < GOOD_THRESHOLD and price < jet_price:
        return "🟢 GOOD PRICE — CHEAPER THAN JET"

    # Yellow: cheaper than JET, but not below €2.17/L.
    if price < jet_price:
        return "🟡 CHEAPER THAN JET, BUT ABOVE GOOD THRESHOLD"

    # Not cheaper than JET: never mark it green.
    if price < GOOD_THRESHOLD:
        return "⚪ BELOW €2.17, BUT NOT CHEAPER THAN JET"

    return "⚪ NOT CHEAPER THAN JET"


# ============================================================
# EMAIL CONTENT
# ============================================================

def format_alternative(station, jet_price):
    price = diesel_price(station)
    status = classify_station(price, jet_price)

    return "\n".join([
        station_name(station),
        f"Diesel: {format_price(price)}",
        f"Status: {status}",
        f"Distance: {distance(station):.2f} km",
        f"Address: {station_address(station)}",
        f"Map: {maps_link(station)}",
    ])


def build_email(all_stations, jet, alternatives, changed_stations):
    jet_price = diesel_price(jet)

    lines = [
        "DIESEL PRICE COMPARISON",
        "=" * 38,
        "",
        "YOUR REFERENCE STATION — JET DIETZENBACH",
        "-" * 38,
        station_name(jet),
        f"Diesel: {format_price(jet.get('diesel'))}",
        f"E5: {format_price(jet.get('e5'))}",
        f"E10: {format_price(jet.get('e10'))}",
        f"Distance: {distance(jet):.2f} km",
        f"Address: {station_address(jet)}",
        f"Map: {maps_link(jet)}",
        "",
        "ARAL AND SHELL — DIESEL ONLY",
        "-" * 38,
    ]

    if not alternatives:
        lines.append("No Aral or Shell alternatives with diesel prices were found within 5 km.")
    else:
        for index, station in enumerate(alternatives, start=1):
            lines.extend([
                "",
                f"STATION {index}",
                format_alternative(station, jet_price),
            ])

    if changed_stations:
        lines.extend([
            "",
            "DIESEL PRICE CHANGES",
            "-" * 38,
        ])

        for item in sorted(changed_stations, key=lambda entry: entry["new_price"]):
            change = item["new_price"] - item["old_price"]

            if change < 0:
                description = f"Decreased by {abs(change):.3f} €/L"
            elif change > 0:
                description = f"Increased by {change:.3f} €/L"
            else:
                description = "Unchanged"

            lines.extend([
                "",
                item["name"],
                f"Diesel: {format_price(item['new_price'])}",
                f"Previous: {format_price(item['old_price'])}",
                f"Change: {description}",
                f"Map: {item['map']}",
            ])

    lines.extend([
        "",
        "=" * 38,
        f"Search radius: {RADIUS_KM:.1f} km",
        f"Green: below {GOOD_THRESHOLD:.3f} €/L AND cheaper than JET",
        f"Yellow: cheaper than JET but not meeting the green rule",
        f"Red: {HIGH_THRESHOLD:.3f} €/L or higher",
        "",
        "Only diesel is shown for Aral and Shell.",
        "JET shows Diesel, E5 and E10.",
        "No savings calculations are included.",
        "Prices are supplied by Tankerkönig and can change before arrival.",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    time.sleep(random.randint(1, 5))

    state = load_state()
    all_stations = list_nearby_stations()

    jet = pick_jet_station(all_stations, state)

    if diesel_price(jet) is None:
        raise RuntimeError("JET diesel price unavailable.")

    alternatives = [
        station
        for station in valid_diesel_stations(all_stations)
        if station.get("id") != jet.get("id")
    ]

    # Show exactly up to three alternatives, ranked by diesel price.
    alternatives.sort(
        key=lambda station: (diesel_price(station), distance(station))
    )
    alternatives = alternatives[:3]

    monitored = [jet] + alternatives

    previous_prices = state.get("diesel_prices_by_station", {})
    if not isinstance(previous_prices, dict):
        previous_prices = {}

    initial_run = not previous_prices
    current_prices = {}
    changed_stations = []

    for station in monitored:
        station_id = station["id"]
        price = diesel_price(station)

        if price is None:
            continue

        current_prices[station_id] = price

        if initial_run:
            continue

        old_price = previous_prices.get(station_id)

        if old_price is None:
            continue

        try:
            old_price = float(old_price)
        except (TypeError, ValueError):
            continue

        if price != old_price:
            changed_stations.append({
                "id": station_id,
                "name": station_name(station),
                "old_price": old_price,
                "new_price": price,
                "map": maps_link(station),
            })

    if initial_run or changed_stations:
        body = build_email(
            all_stations=all_stations,
            jet=jet,
            alternatives=alternatives,
            changed_stations=changed_stations,
        )

        if initial_run:
            subject = "⛽ Diesel Watcher — Initial Comparison"
        else:
            jet_price = diesel_price(jet)
            subject = (
                f"⛽ Diesel price changed — JET {jet_price:.3f} €/L"
            )

        send_email(subject, body)

    state["station_id"] = jet["id"]
    state["station_meta"] = jet
    state["diesel_prices_by_station"] = current_prices
    state["last_diesel"] = diesel_price(jet)
    state["last_check_unix"] = int(time.time())

    save_state(state)

    print(f"JET reference: {station_name(jet)}")
    print(f"JET diesel: {diesel_price(jet):.3f} €/L")
    print(f"Radius: {RADIUS_KM:.1f} km")
    print(f"Alternative stations shown: {len(alternatives)}")
    print(f"Changed prices: {len(changed_stations)}")


if __name__ == "__main__":
    main()
