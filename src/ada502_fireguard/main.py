import requests
from flask import Flask, render_template, jsonify, request, url_for, session
import folium
import frcm  # Dette er fire risk-kalkulatoren fra Lars
import pandas as pd
import io
# Denne brukes for å håndtere tidskodene i værdataen fra MET
from dateutil import parser
import csv
import json  # Kun for testning, kan fjernes
from apscheduler.schedulers.background import BackgroundScheduler  # For å trigge emails
import atexit
from datetime import datetime
import smtplib
from email.message import EmailMessage
import os   # Dette har med sikker lagring av passord til fireguard email
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Variables
VALID_USERNAME = 'test'
VALID_PASSWORD = 'test'

m = folium.Map(location=[62.972077, 10.395563], zoom_start=6)

#---------------Sende Emails--------------------
# Example users used to create emails, will be changed later
users_with_favorites = [
    {
        "email": "669866@stud.hvl.no",
        "favorites": ["Place A", "Place B", "Place C"],
    },
    {
        "email": "jonasedland@gmail.com",
        "favorites": ["Place D", "Place E"],
    },
]

# Configuration (loaded from environment variables)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")


def build_email_for_user(user: dict) -> EmailMessage:
    #Makes the email the users will recive
    recipient_email = user["email"]
    favorites = user.get("favorites", [])

    # Create a simple text listing their favorites
    if favorites:
        favorites_list = "\n".join(f"- {place}" for place in favorites)
        body = (
            "Hello,\n\n"
            "Here are your favorited places:\n\n"
            f"{favorites_list}\n\n"
            "Best regards,\n"
            "FireGuard"
        )
    else:
        body = (
            "Hello,\n\n"
            "You currently have no favorited places.\n\n"
            "Best regards,\n"
            "FireGuard"
        )

    msg = EmailMessage()
    msg["Subject"] = "FireGuard – Daily notification"
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient_email
    msg.set_content(body)

    return msg

def send_daily_notification():
    #Sends the email
    print(f"[{datetime.now()}] Running daily notification task...")

    if not users_with_favorites:
        print(f"[{datetime.now()}] No users to notify.")
        return

    try:
        # One SMTP connection for all emails
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)

            for user in users_with_favorites:
                msg = build_email_for_user(user)
                try:
                    server.send_message(msg)
                    print(
                        f"[{datetime.now()}] Email sent to {user['email']}"
                    )
                except Exception as e_user:
                    print(
                        f"[{datetime.now()}] Failed to send email to "
                        f"{user['email']}: {e_user}"
                    )

    except Exception as e:
        print(f"[{datetime.now()}] SMTP connection/login failed: {e}")


# Initialize the scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(
    func=send_daily_notification,
    trigger="cron",
    hour=0,
    minute=5,
    id="daily_notification",
    name="Daily notification at midnight",
    replace_existing=True
)
scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())
#---------------Sende Emails--------------------


@app.route("/weather")
def get_weather():
    lat = request.args.get("lat")
    lon = request.args.get("lon")

    if not lat or not lon:
        return jsonify({"error": "Missing coordinates"}), 400

    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"

    headers = {
        "User-Agent": "FireGuard/1.0 668523@stud.hvl.no"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch weather"}), 500

    all_data = response.json()

    # -----Dette er her for testing---
    # path = "C:\\Users\\jonas\\Desktop\\test\\bergen_2026_01_09.json"
    # with open(path, "r", encoding="utf-8") as f:
    #    all_data = json.load(f)
    # --------------------------------------------

    geo_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    geo_res = requests.get(geo_url, headers=headers).json()
    addr = geo_res.get("address", {})

    place = addr.get("suburb") or addr.get("village") or addr.get(
        "town") or addr.get("city") or "Unknown place"
    county = addr.get("municipality") or addr.get(
        "city") or "Unknown municipality"

    # --------------Fire risk-kalkulering--------------------
    # For å returnere værdata for i dag
    current = all_data["properties"]["timeseries"][0]["data"]["instant"]["details"]

    timeseries = all_data["properties"]["timeseries"]

    weather_points = []

    for entry in timeseries:
        # Noe GPT-kode som gjør json om til en filtype som kalkulatoren kan bruke senere
        timestamp = parser.isoparse(entry["time"])

        details = entry["data"]["instant"]["details"]

        temp = float(details["air_temperature"])
        hum = float(details["relative_humidity"])
        wind = float(details["wind_speed"])

        weather_points.append(
            frcm.WeatherDataPoint(
                temperature=temp,
                humidity=hum,
                wind_speed=wind,
                timestamp=timestamp
            )
        )

    # Funksjon fra FRC for å få dataen på en form den kan kalkulere med
    weatherData = frcm.WeatherData(data=weather_points)

    # Time to flashover, i forskjellige formater som kan benyttes:
    # Kalkulerer ttf og får ut en rar datatype
    ttf_customClass = frcm.compute(weatherData)
    ttf_text = str(ttf_customClass)  # Gjør resultatetne om til en rein string
    # Gjør stringen om til en csv-fil for senere bruk
    ttf_csv = pd.read_csv(io.StringIO(ttf_text), parse_dates=["timestamp"])

    # Blanding av ny og gammel kode. Tid og fire riske for nå-tid lages for seg selv, mens fremtidig tid kommer senere
    first_timestamp_pd = ttf_csv["timestamp"].iloc[1]
    first_timestamp_string = first_timestamp_pd.strftime(
        "%d. %B, %H:%M").lower()

    first_ttf_float = float(ttf_csv["ttf"].iloc[1])

    # Lager tekst som viser fremtidige tider
    ttf_future = ""
    for i in range(2, min(11, len(ttf_csv))):
        timestamp = ttf_csv["timestamp"].iloc[i]
        ttf_value = float(ttf_csv["ttf"].iloc[i])
        ttf_future += f"{timestamp.strftime('%d. %B, %H:%M').lower()} {ttf_value:.2f} min<br>"
    # ------------------------------------------------------

    # Setter alt inn i en JSON som html kan bruke
    return jsonify({
        "place": place,
        "county": county,
        "temperature": current["air_temperature"],
        "wind_speed": current["wind_speed"],
        "humidity": current["relative_humidity"],
        "timestamp": first_timestamp_string,
        "ttf_current": f"{first_ttf_float:.2f}",
        "ttf_future": ttf_future
    })


@app.route('/', methods=['GET', 'POST'])
def index():

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if username == VALID_USERNAME and password == VALID_PASSWORD:
            session['username'] = username
            return jsonify({"success": True, "message": "Login successful"})
        else:
            return jsonify({"success": False, "message": "Username and password do not match"})

    return render_template('index.html')


@app.route('/set-guest', methods=['POST'])
def set_guest():
    session['username'] = "Guest"
    return '', 204


@app.route('/mainpage')
def mainpage():
    username = session.get('username', 'Guest')
    return render_template('mainpage.html', username=username)


@app.route('/trigger-daily-task', methods=['POST'])
def trigger_daily_task():
    """
    Manual endpoint to trigger the daily notification task.
    Useful for testing without waiting until midnight.
    """
    try:
        send_daily_notification()
        return jsonify({"success": True, "message": "Daily task executed successfully"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
