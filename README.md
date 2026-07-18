# ⛽ Fuel Price Monitoring & Alert System

An automated fuel price monitoring system built with **Python** that tracks real-time diesel prices using the **Tankerkönig API** and sends email notifications when prices change or reach user-defined thresholds. The application is fully automated using **GitHub Actions**, allowing it to run every 5 minutes without requiring a local machine.

---

## 📌 Features

- Monitor a selected **JET fuel station** in Dietzenbach.
- Fetch live fuel prices using the **Tankerkönig REST API**.
- Track **Diesel**, **E5**, and **E10** prices.
- Receive email alerts when:
  - Diesel price drops below a defined threshold.
  - Diesel price rises above a defined threshold.
  - Fuel price changes.
- Display nearby cheapest fuel stations within a configurable radius.
- Include Google Maps links for easy navigation.
- Store the previous fuel price using JSON to avoid duplicate notifications.
- Execute automatically every **5 minutes** using GitHub Actions.

---

## 🛠️ Technologies Used

- Python
- Git & GitHub
- GitHub Actions
- REST API
- Tankerkönig API
- JSON
- SMTP (Email)
- Environment Variables

---

## 📂 Project Structure

```
fuel-watcher/
│
├── .github/
│   └── workflows/
│       └── main.yml
│
├── watch_fuel_real.py
├── requirements.txt
├── README.md
└── state.json
```

---

## ⚙️ How It Works

```
GitHub Actions
        │
        ▼
Runs every 5 minutes
        │
        ▼
Tankerkönig REST API
        │
        ▼
Retrieve latest fuel prices
        │
        ▼
Compare with previous state
        │
        ▼
Generate email notification
        │
        ▼
Send alert to user
```

---

## 📧 Example Notification

The application sends detailed email notifications including:

- Current Diesel, E5 and E10 prices
- Price change information
- Low-price and high-price alerts
- Nearby cheapest fuel stations
- Google Maps links for all stations

---

## 🔧 Configuration

The project uses GitHub Secrets / environment variables for sensitive information.

Example:

```
TANKERKOENIG_API_KEY
SMTP_USER
SMTP_PASS
EMAIL_TO
LOW_THRESHOLD
HIGH_THRESHOLD
RADIUS_KM
EMAIL_ON_ANY_CHANGE
```

No API keys or passwords are stored inside the source code.

---

## 💡 Skills Demonstrated

This project demonstrates practical software engineering skills including:

- Python Programming
- REST API Integration
- Automation
- Scheduled Workflows
- GitHub Actions
- JSON Data Processing
- Email Automation
- Configuration Management
- State Persistence
- Error Handling
- Version Control with Git

---

This project was developed as a personal software engineering project for learning automation, API integration, and cloud-based task scheduling.
