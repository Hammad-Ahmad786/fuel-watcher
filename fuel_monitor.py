import os
import json
import time
import random
import smtplib
from email.message import EmailMessage

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
RADIUS_KM = float(os.environ.get("RADIUS_KM", "10"))

STREET_HINTS = [
    x.strip().lower()
    for x in os.environ.get(
        "STREET_HINTS", "elisabeth,selbert"
    ).split(",")
    if x.strip()
]

STATE_FILE = "state.json"

LIST_URL = "https://creativecommons.tankerkoenig.de/json/list.php"


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
            return json.load(file)
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

    response = requests.get(
        LIST_URL,
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(f"Tankerkönig API error: {data}")

    return data.get("stations", [])


# ============================================================
# STATION HELPERS
# ============================================================

def is_jet(station):
    name = (station.get("name") or "").lower()
    brand = (station.get("brand") or "").lower()

    return "jet" in name or "jet" in brand


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

    if value <= 0:
        return None

    return value


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

    from urllib.parse import quote_plus

    return (
        "https://www.google.com/maps/search/?api=1&query="
        + quote_plus(str(query))
    )


def find_jet(stations, saved_state):
    # Prefer the previously selected JET station so the reference
    # station does not change unexpectedly between runs.
    saved_id = saved_state.get("station_id")

    if saved_id:
        for station in stations:
            if station.get("id") == saved_id and is_jet(station):
                return station

    candidates = []

    for station in stations:
        if not is_jet(station):
            continue

        street = (station.get("street") or "").lower()
        score = sum(10 for hint in STREET_HINTS if hint in street)

        candidates.append((score, -distance(station), station))

    if not candidates:
        raise RuntimeError(
            "Could not find the JET reference station. "
            "Check the search coordinates and radius."
        )

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    return candidates[0][2]


def valid_diesel_stations(stations):
    result = []

    for station in stations:
        if not station.get("id"):
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


def format_station(station, jet_price):
    price = diesel_price(station)

    lines = [
        station_name(station),
        f"Diesel: {price:.3f} €/L",
        f"Distance: {distance(station):.2f} km",
        f"Address: {station_address(station)}",
    ]

    if price < jet_price:
        saving = jet_price - price

        lines.append("🟢 CHEAPER THAN JET")
        lines.append(f"Savings: {saving:.3f} €/L")
        lines.append(f"Savings on 50 litres: {saving * 50:.2f} €")
    elif price == jet_price:
        lines.append("Same price as JET")
    else:
        lines.append(f"{price - jet_price:.3f} €/L more expensive than JET")

    lines.append(f"Map: {maps_link(station)}")

    return "\n".join(lines)


def build_email(stations, jet, changed_stations, initial_run):
    jet_price = diesel_price(jet)

    # Sort all available diesel stations by price, then distance.
    ranked = sorted(
        valid_diesel_stations(stations),
        key=lambda station: (
            diesel_price(station),
            distance(station),
        ),
    )

    # Show up to three alternatives, excluding JET.
    alternatives = [
        station
        for station in ranked
        if station.get("id") != jet.get("id")
    ][:3]

    lines = [
        "DIESEL PRICE COMPARISON",
        "=" * 35,
        "",
        "YOUR REFERENCE STATION — JET",
        "-" * 35,
        station_name(jet),
        f"Diesel: {jet_price:.3f} €/L",
        f"Status: {price_status(jet_price)}",
        f"Address: {station_address(jet)}",
        f"Map: {maps_link(jet)}",
        "",
        "THREE CHEAPEST NEARBY ALTERNATIVES",
        "-" * 35,
    ]

    if not alternatives:
        lines.append("No other stations with valid diesel prices were found.")
    else:
        for index, station in enumerate(alternatives, start=1):
            lines.append("")
            lines.append(f"OPTION {index}")
            lines.append(format_station(station, jet_price))

    cheaper = [
        station for station in alternatives
        if diesel_price(station) < jet_price
    ]

    lines.extend([
        "",
        "RECOMMENDATION",
        "-" * 35,
    ])

    if cheaper:
        best = cheaper[0]
        saving = jet_price - diesel_price(best)

        lines.extend([
            "🟢 The cheapest alternative shown is cheaper than JET.",
            station_name(best),
            f"Diesel: {diesel_price(best):.3f} €/L",
            f"You save {saving:.3f} €/L compared with JET.",
            f"Estimated saving on 50 litres: {saving * 50:.2f} €",
            f"Map: {maps_link(best)}",
        ])
    else:
        lines.append(
            "None of the three alternatives shown is cheaper than JET. "
            "JET is the best choice among these stations."
        )

    if changed_stations:
        lines.extend([
            "",
            "DIESEL PRICE CHANGES DETECTED",
            "-" * 35,
        ])

        for item in sorted(
            changed_stations,
            key=lambda item: item["new_price"],
        ):
            difference = item["new_price"] - item["old_price"]

            if difference < 0:
                change_text = f"decreased by {abs(difference):.3f} €/L"
            elif difference > 0:
                change_text = f"increased by {difference:.3f} €/L"
            else:
                change_text = "unchanged"

            lines.extend([
                "",
                item["name"],
                f"Diesel: {item['new_price']:.3f} €/L",
                f"Previous: {item['old_price']:.3f} €/L",
                f"Change: {change_text}",
                f"Map: {item['map']}",
            ])

    lines.extend([
        "",
        "=" * 35,
        f"Search radius: {RADIUS_KM:.1f} km",
        f"Cheap diesel: {LOW_THRESHOLD:.3f} €/L or less",
        f"High diesel price: above {HIGH_THRESHOLD:.3f} €/L",
        "",
        "Only diesel prices are shown.",
        "Prices are based on Tankerkönig data and may change before arrival.",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    time.sleep(random.randint(1, 5))

    state = load_state()

    stations = list_nearby_stations()
    jet = find_jet(stations, state)

    if diesel_price(jet) is None:
        raise RuntimeError(
            "JET diesel price is unavailable. No state changes were saved."
        )

    valid = valid_diesel_stations(stations)

    if not valid:
        raise RuntimeError("No valid diesel prices were returned.")

    previous = state.get("diesel_prices_by_station", {})

    if not isinstance(previous, dict):
        previous = {}

    initial_run = not previous
    current = {}
    changed = []

    for station in valid:
        station_id = station["id"]
        price = diesel_price(station)

        current[station_id] = price

        # First run establishes the baseline.
        if initial_run:
            continue

        old_price = previous.get(station_id)

        if old_price is None:
            # A newly discovered station is recorded first.
            continue

        try:
            old_price = float(old_price)
        except (TypeError, ValueError):
            continue

        if price != old_price:
            changed.append({
                "id": station_id,
                "name": station_name(station),
                "old_price": old_price,
                "new_price": price,
                "map": maps_link(station),
            })

    # First run: send a starting comparison.
    # Later runs: send only when a known station's price changes.
    if initial_run or changed:
        body = build_email(
            stations=stations,
            jet=jet,
            changed_stations=changed,
            initial_run=initial_run,
        )

        if initial_run:
            subject = "⛽ Diesel Watcher — Initial Comparison"
        else:
            jet_price = diesel_price(jet)
            cheapest = min(
                valid,
                key=lambda station: (
                    diesel_price(station),
                    distance(station),
                ),
            )

            cheapest_price = diesel_price(cheapest)

            if cheapest_price <= LOW_THRESHOLD:
                subject = f"🟢 CHEAP DIESEL — {cheapest_price:.3f} €/L"
            elif cheapest_price > HIGH_THRESHOLD:
                subject = f"🔴 HIGH DIESEL PRICE — {cheapest_price:.3f} €/L"
            else:
                subject = f"⛽ Diesel price changed — JET {jet_price:.3f} €/L"

        send_email(subject, body)

    # Save the latest prices only after the email has succeeded, if one
    # was required. This lets the next run retry if email sending fails.
    state["station_id"] = jet["id"]
    state["station_meta"] = jet
    state["diesel_prices_by_station"] = current
    state["last_diesel"] = diesel_price(jet)
    state["last_check_unix"] = int(time.time())

    save_state(state)

    print(f"Stations with diesel prices: {len(valid)}")
    print(f"JET diesel: {diesel_price(jet):.3f} €/L")
    print(f"Search radius: {RADIUS_KM:.1f} km")
    print(f"Changed station prices: {len(changed)}")


if __name__ == "__main__":
    main()
