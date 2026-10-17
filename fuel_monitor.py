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

LOW_THRESHOLD = float(os.environ.get("LOW_THRESHOLD", "2.200"))
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
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    os.replace(temp_file, STATE_FILE)


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


def distance(station):
    try:
        return float(station.get("dist") or 999)
    except (TypeError, ValueError):
        return 999


def diesel_price(station):
    value = station.get("diesel")

    if value is None:
        return None

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def format_price(value):
    if value is None:
        return "Unavailable"

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


def pick_jet_station(stations, state):
    # Keep using the previously selected JET station if it is
    # still returned by the API.
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
            "JET reference station not found within the radius. "
            "Check LAT, LNG, RADIUS_KM and STREET_HINTS."
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
# EMAIL CONTENT
# ============================================================

def price_status(price):
    if price <= LOW_THRESHOLD:
        return "🟢 CHEAP DIESEL"

    if price > HIGH_THRESHOLD:
        return "🔴 HIGH DIESEL PRICE"

    return "🟡 DIESEL PRICE"


def format_alternative(station, jet_price):
    price = diesel_price(station)

    lines = [
        station_name(station),
        f"Diesel: {format_price(price)}",
        f"Distance: {distance(station):.2f} km",
        f"Address: {station_address(station)}",
    ]

    if price < jet_price:
        saving = jet_price - price

        lines.extend([
            "🟢 CHEAPER THAN JET",
            f"You save: {saving:.3f} €/L",
            f"Saving on 50 litres: {saving * 50:.2f} €",
        ])
    elif price == jet_price:
        lines.append("Same diesel price as JET")
    else:
        lines.append(
            f"{price - jet_price:.3f} €/L more expensive than JET"
        )

    lines.append(f"Map: {maps_link(station)}")

    return "\n".join(lines)


def build_email(stations, jet, changed_stations, initial_run):
    jet_diesel = diesel_price(jet)

    # Alternatives are Aral and Shell only. JET remains the reference.
    alternatives = [
        station for station in valid_diesel_stations(stations)
        if station.get("id") != jet.get("id")
    ]

    alternatives.sort(
        key=lambda station: (
            diesel_price(station),
            distance(station),
        )
    )

    # Display up to three cheapest Aral/Shell alternatives.
    alternatives = alternatives[:3]

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
        f"Status: {price_status(jet_diesel)}",
        f"Distance: {distance(jet):.2f} km",
        f"Address: {station_address(jet)}",
        f"Map: {maps_link(jet)}",
        "",
        "ARAL AND SHELL — DIESEL ONLY",
        "-" * 38,
    ]

    if not alternatives:
        lines.append(
            "No Aral or Shell alternatives with valid diesel prices "
            "were found within 5 km."
        )
    else:
        for index, station in enumerate(alternatives, start=1):
            lines.extend([
                "",
                f"ALTERNATIVE {index}",
                format_alternative(station, jet_diesel),
            ])

    cheaper = [
        station for station in alternatives
        if diesel_price(station) < jet_diesel
    ]

    lines.extend([
        "",
        "RECOMMENDATION",
        "-" * 38,
    ])

    if cheaper:
        best = cheaper[0]
        saving = jet_diesel - diesel_price(best)

        lines.extend([
            "🟢 CHEAPEST SHOWN ALTERNATIVE BELOW JET PRICE",
            station_name(best),
            f"Diesel: {format_price(best.get('diesel'))}",
            f"Cheaper than JET by {saving:.3f} €/L",
            f"Estimated saving on 50 litres: {saving * 50:.2f} €",
            f"Address: {station_address(best)}",
            f"Map: {maps_link(best)}",
        ])
    else:
        lines.append(
            "None of the displayed Aral/Shell stations is cheaper than JET. "
            "JET is the best-priced option among the stations shown."
        )

    if changed_stations:
        lines.extend([
            "",
            "DIESEL PRICE CHANGES",
            "-" * 38,
        ])

        for item in sorted(
            changed_stations,
            key=lambda entry: entry["new_price"],
        ):
            difference = item["new_price"] - item["old_price"]

            if difference < 0:
                change = f"decreased by {abs(difference):.3f} €/L"
            elif difference > 0:
                change = f"increased by {difference:.3f} €/L"
            else:
                change = "unchanged"

            lines.extend([
                "",
                item["name"],
                f"Diesel: {format_price(item['new_price'])}",
                f"Previous: {format_price(item['old_price'])}",
                f"Change: {change}",
                f"Map: {item['map']}",
            ])

    lines.extend([
        "",
        "=" * 38,
        f"Search radius: {RADIUS_KM:.1f} km",
        f"Cheap threshold: {LOW_THRESHOLD:.3f} €/L or less",
        f"High threshold: above {HIGH_THRESHOLD:.3f} €/L",
        "",
        "JET displays Diesel, E5 and E10.",
        "Aral and Shell display diesel only.",
        "Prices are provided by Tankerkönig and may change before arrival.",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    time.sleep(random.randint(1, 5))

    state = load_state()
    all_stations = list_nearby_stations()

    # Select the reference JET from all returned stations.
    jet = pick_jet_station(all_stations, state)

    if diesel_price(jet) is None:
        raise RuntimeError(
            "JET diesel price is unavailable. "
            "No price comparison was sent."
        )

    # Only JET, Aral and Shell with valid diesel prices are tracked.
    monitored_stations = valid_diesel_stations(all_stations)

    # Ensure JET is included even if its brand field is unusual.
    if not any(s.get("id") == jet.get("id") for s in monitored_stations):
        monitored_stations.append(jet)

    previous_prices = state.get("diesel_prices_by_station", {})

    if not isinstance(previous_prices, dict):
        previous_prices = {}

    initial_run = not previous_prices
    current_prices = {}
    changed_stations = []

    for station in monitored_stations:
        station_id = station["id"]
        price = diesel_price(station)

        if price is None:
            continue

        current_prices[station_id] = price

        if initial_run:
            continue

        old_price = previous_prices.get(station_id)

        # A newly discovered station establishes its baseline first.
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
            stations=all_stations,
            jet=jet,
            changed_stations=changed_stations,
            initial_run=initial_run,
        )

        if initial_run:
            subject = "⛽ Diesel Watcher — Initial Comparison"
        else:
            cheapest = min(
                monitored_stations,
                key=lambda station: (
                    diesel_price(station)
                    if diesel_price(station) is not None else float("inf"),
                    distance(station),
                ),
            )

            cheapest_price = diesel_price(cheapest)

            if cheapest_price is not None and cheapest_price <= LOW_THRESHOLD:
                subject = f"🟢 CHEAP DIESEL — {cheapest_price:.3f} €/L"
            elif cheapest_price is not None and cheapest_price > HIGH_THRESHOLD:
                subject = f"🔴 HIGH DIESEL PRICE — {cheapest_price:.3f} €/L"
            else:
                subject = "⛽ Diesel price changed nearby"

        send_email(subject, body)

    # Save the current baseline after any required email was sent.
    state["station_id"] = jet["id"]
    state["station_meta"] = jet
    state["diesel_prices_by_station"] = current_prices
    state["last_diesel"] = diesel_price(jet)
    state["last_check_unix"] = int(time.time())

    save_state(state)

    print(f"Reference JET: {station_name(jet)}")
    print(f"JET diesel: {diesel_price(jet):.3f} €/L")
    print(f"Search radius: {RADIUS_KM:.1f} km")
    print(f"Monitored stations: {len(monitored_stations)}")
    print(f"Diesel price changes: {len(changed_stations)}")


if __name__ == "__main__":
    main()
