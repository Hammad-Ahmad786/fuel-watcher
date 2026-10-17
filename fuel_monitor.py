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
RADIUS_KM = float(os.environ.get("RADIUS_KM", "10"))

STREET_HINTS = [
    value.strip().lower()
    for value in os.environ.get(
        "STREET_HINTS", "elisabeth,selbert"
    ).split(",")
    if value.strip()
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

    response = requests.get(
        LIST_URL,
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"Tankerkönig API error: {data}"
        )

    return data.get("stations", [])


# ============================================================
# STATION HELPERS
# ============================================================

def is_jet_station(station):
    name = (station.get("name") or "").lower()
    brand = (station.get("brand") or "").lower()

    return "jet" in name or "jet" in brand


def pick_jet_station(stations):
    candidates = []

    for station in stations:
        if not is_jet_station(station):
            continue

        street = (station.get("street") or "").lower()

        score = sum(
            10 for hint in STREET_HINTS if hint in street
        )

        try:
            distance = float(station.get("dist") or 999)
        except (TypeError, ValueError):
            distance = 999

        candidates.append((score, -distance, station))

    if not candidates:
        raise RuntimeError(
            "No JET station found in the search radius. "
            "Check LAT, LNG, RADIUS_KM and STREET_HINTS."
        )

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    return candidates[0][2]


def maps_link(station):
    latitude = station.get("lat")
    longitude = station.get("lng")

    if latitude is not None and longitude is not None:
        query = f"{latitude},{longitude}"
    else:
        street = station.get("street") or ""
        house_number = station.get("houseNumber") or ""
        postcode = station.get("postCode") or ""
        place = station.get("place") or ""

        query = quote_plus(
            f"{street} {house_number}, {postcode} {place}".strip()
        )

    return f"https://www.google.com/maps/search/?api=1&query={query}"


def station_name(station):
    name = station.get("name") or station.get("brand") or "Unknown station"
    place = station.get("place") or ""

    return f"{name}, {place}".strip(", ")


def station_address(station):
    street = station.get("street") or ""
    house_number = station.get("houseNumber") or ""
    postcode = station.get("postCode") or ""
    place = station.get("place") or ""

    address = f"{street} {house_number}, {postcode} {place}"
    return address.strip(" ,")


def diesel_price(station):
    price = station.get("diesel")

    if price is None:
        return None

    try:
        price = float(price)
    except (TypeError, ValueError):
        return None

    if price <= 0:
        return None

    return price


def distance_km(station):
    try:
        return float(station.get("dist") or 999)
    except (TypeError, ValueError):
        return 999


def format_price(price):
    if price is None:
        return "Unavailable"

    return f"{price:.3f} €/L"


def price_category(price):
    if price <= LOW_THRESHOLD:
        return "🟢 CHEAP DIESEL"

    if price > HIGH_THRESHOLD:
        return "🔴 HIGH DIESEL PRICE"

    return "🟡 DIESEL PRICE"


# ============================================================
# DIESEL COMPARISON
# ============================================================

def get_valid_diesel_stations(stations):
    valid = []

    for station in stations:
        price = diesel_price(station)

        if price is None:
            continue

        if not station.get("id"):
            continue

        valid.append(station)

    return valid


def cheapest_station(stations):
    valid = get_valid_diesel_stations(stations)

    if not valid:
        return None

    return min(
        valid,
        key=lambda station: (
            diesel_price(station),
            distance_km(station),
        ),
    )


def build_email_body(stations, jet, changed_stations, first_run):
    valid_stations = get_valid_diesel_stations(stations)

    jet_price = diesel_price(jet)
    cheapest = cheapest_station(valid_stations)

    lines = []

    lines.append("DIESEL PRICE MONITOR")
    lines.append("=" * 35)
    lines.append("")

    if first_run:
        lines.append("Initial price snapshot")
    else:
        lines.append("Diesel prices have changed at monitored stations.")

    lines.append("")
    lines.append("YOUR REFERENCE STATION: JET")
    lines.append("-" * 35)
    lines.append(f"Station: {station_name(jet)}")
    lines.append(f"Diesel: {format_price(jet_price)}")
    lines.append(f"Address: {station_address(jet)}")
    lines.append(f"Map: {maps_link(jet)}")

    if jet_price is not None:
        lines.append(f"Status: {price_category(jet_price)}")

    lines.append("")
    lines.append("CHEAPEST NEARBY DIESEL")
    lines.append("-" * 35)

    if cheapest is None:
        lines.append("No valid diesel prices were returned.")
    else:
        cheapest_price = diesel_price(cheapest)

        lines.append(f"Station: {station_name(cheapest)}")
        lines.append(f"Diesel: {format_price(cheapest_price)}")
        lines.append(
            f"Distance: {distance_km(cheapest):.2f} km"
        )
        lines.append(f"Address: {station_address(cheapest)}")
        lines.append(f"Map: {maps_link(cheapest)}")
        lines.append(f"Status: {price_category(cheapest_price)}")

        if jet_price is not None:
            savings_per_litre = jet_price - cheapest_price

            if savings_per_litre > 0:
                lines.append(
                    f"Savings vs JET: {savings_per_litre:.3f} €/L"
                )
                lines.append(
                    f"Savings on 50 litres: "
                    f"{savings_per_litre * 50:.2f} €"
                )
            elif savings_per_litre < 0:
                lines.append(
                    f"JET is cheaper by "
                    f"{abs(savings_per_litre):.3f} €/L."
                )
            else:
                lines.append("Same diesel price as JET.")

    if changed_stations:
        lines.append("")
        lines.append("STATIONS WITH CHANGED DIESEL PRICES")
        lines.append("-" * 35)

        changed_stations = sorted(
            changed_stations,
            key=lambda item: item["new_price"],
        )

        for item in changed_stations:
            lines.append("")
            lines.append(item["name"])
            lines.append(
                f"Price: {format_price(item['new_price'])}"
            )

            if item["old_price"] is not None:
                difference = item["new_price"] - item["old_price"]

                if difference < 0:
                    direction = "decreased"
                elif difference > 0:
                    direction = "increased"
                else:
                    direction = "unchanged"

                lines.append(
                    f"Change: {item['old_price']:.3f} "
                    f"→ {item['new_price']:.3f} €/L "
                    f"({direction})"
                )
            else:
                lines.append("Change: first recorded price")

            lines.append(
                f"Distance: {item['distance']:.2f} km"
            )
            lines.append(f"Address: {item['address']}")
            lines.append(f"Map: {item['map']}")

    lines.append("")
    lines.append("=" * 35)
    lines.append(
        f"Search radius: {RADIUS_KM:.1f} km"
    )
    lines.append(
        f"Cheap threshold: {LOW_THRESHOLD:.3f} €/L or less"
    )
    lines.append(
        f"High-price threshold: above {HIGH_THRESHOLD:.3f} €/L"
    )
    lines.append("")
    lines.append(
        "Prices are based on the latest data returned by Tankerkönig. "
        "Check the price before travelling."
    )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    time.sleep(random.randint(1, 5))

    state = load_state()

    stations = list_nearby_stations()
    valid_stations = get_valid_diesel_stations(stations)

    if not valid_stations:
        raise RuntimeError(
            "No stations with valid diesel prices were returned."
        )

    jet = pick_jet_station(stations)

    if diesel_price(jet) is None:
        raise RuntimeError(
            "JET was found, but its diesel price is unavailable. "
            "Will retry on the next scheduled run."
        )

    # Preserve the selected JET station.
    state["station_id"] = jet["id"]
    state["station_meta"] = jet

    # Remember the diesel price of every station separately.
    previous_prices = state.get("diesel_prices_by_station", {})

    if not isinstance(previous_prices, dict):
        previous_prices = {}

    first_run = len(previous_prices) == 0
    current_prices = {}
    changed_stations = []

    for station in valid_stations:
        station_id = station["id"]
        price = diesel_price(station)

        if price is None:
            continue

        current_prices[station_id] = price

        previous_price = previous_prices.get(station_id)

        if previous_price is not None:
            try:
                previous_price = float(previous_price)
            except (TypeError, ValueError):
                previous_price = None

        if first_run:
            continue

        # A new station entering the radius is recorded as a new
        # baseline, not automatically treated as a price change.
        if previous_price is None:
            continue

        if price != previous_price:
            changed_stations.append({
                "id": station_id,
                "name": station_name(station),
                "old_price": previous_price,
                "new_price": price,
                "distance": distance_km(station),
                "address": station_address(station),
                "map": maps_link(station),
            })

    # Send one initial summary, then email only when a known station's
    # diesel price changes.
    if first_run or changed_stations:
        body = build_email_body(
            stations=stations,
            jet=jet,
            changed_stations=changed_stations,
            first_run=first_run,
        )

        if first_run:
            subject = "⛽ Diesel Watcher — Initial Price Summary"
        else:
            cheapest = cheapest_station(valid_stations)

            if cheapest is not None:
                cheapest_price = diesel_price(cheapest)

                if cheapest_price <= LOW_THRESHOLD:
                    subject = (
                        f"🟢 CHEAP DIESEL — "
                        f"{cheapest_price:.3f} €/L"
                    )
                elif cheapest_price > HIGH_THRESHOLD:
                    subject = (
                        f"🔴 HIGH DIESEL PRICE — "
                        f"{cheapest_price:.3f} €/L"
                    )
                else:
                    subject = (
                        f"⛽ Diesel price changed — "
                        f"{cheapest_price:.3f} €/L"
                    )
            else:
                subject = "⛽ Diesel prices changed nearby"

        send_email(subject, body)

    # Update saved prices only after a successful check and successful
    # email (when an email was required).
    state["diesel_prices_by_station"] = current_prices
    state["last_diesel"] = diesel_price(jet)
    state["last_check_unix"] = int(time.time())

    save_state(state)

    print(f"Stations checked: {len(valid_stations)}")
    print(f"JET diesel: {diesel_price(jet):.3f} €/L")
    print(f"Cheapest diesel: {format_price(diesel_price(cheapest_station(valid_stations)))}")
    print(f"Changed stations: {len(changed_stations)}")


if __name__ == "__main__":
    main()
