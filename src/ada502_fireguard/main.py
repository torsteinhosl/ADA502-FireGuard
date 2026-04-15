import requests
from flask import Flask, render_template, jsonify, request, url_for, session, redirect
import folium
import frcm  # Dette er fire risk-kalkulatoren fra Lars
import pandas as pd
import io
# Denne brukes for å håndtere tidskodene i værdataen fra MET
from dateutil import parser
import csv
from keycloak import KeycloakOpenID
from flask_sqlalchemy import SQLAlchemy

keycloak_openid = KeycloakOpenID(
    server_url="http://158.39.75.130:8080/", #158.39.75.130
    client_id="fireguard-app",
    realm_name="fireguard",
    client_secret_key=None
)
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

m = folium.Map(location=[62.972077, 10.395563], zoom_start=6)

app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://postgres:fireguard@fireguard1.cv6ewuwg64ny.eu-central-1.rds.amazonaws.com:5432/postgres"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

class Fylke(db.Model):
    __tablename__ = "fylke"
    name = db.Column(db.String(20), primary_key=True)

    kommuner = db.relationship("Kommune", backref="fylke")

class Kommune(db.Model):
    __tablename__ = "kommune"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40))
    fylke_name = db.Column(db.String(20), db.ForeignKey("fylke.name"))

    tettsteder = db.relationship("Tettsted", backref="kommune")

class Tettsted(db.Model):
    __tablename__ = "tettsted"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40))
    kommune_id =db.Column(db.Integer, db.ForeignKey("kommune.id"))

class Bruker(db.Model):
    __tablename__ = "bruker"
    keycloak_id = db.Column(db.String(100), primary_key=True)
    brukernavn = db.Column(db.String(50))
    email = db.Column(db.String(75))

class Favoritter(db.Model):
    __tablename__ = "favoritter"
    id = db.Column(db.Integer, primary_key=True)
    bruker_id = db.Column(db.String(100), db.ForeignKey("bruker.keycloak_id"))
    tettsted_id = db.Column(db.Integer, db.ForeignKey("tettsted.id"))

    
# ---------------Sende Emails--------------------
# Example users used to create emails, will be changed later
users_with_favorites = [
    {
        "email": "669866@stud.hvl.no",
        "favorites": [{"lat": 60.36928328136428, "lon": 5.35059928894043}, {"lat": 60.36117711701432, "lon": 5.297470092773437}],
    },
    {
        "email": "jonasedland@gmail.com",
        "favorites": [{"lat": 60.36928328136428, "lon": 5.35059928894043}, {"lat": 60.36117711701432, "lon": 5.297470092773437}],
    },
]

# Configuration (loaded from environment variables)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")


def get_weather_data_for_email(lat, lon):
    # Kaller på calculate_weather_data og formarterer det på en måte som virker for email
    data = calculate_weather_data(lat, lon)
    if data is None:
        return "Failed to fetch weather data"
    # Replace HTML <br> tags with newlines for plain text email
    ttf_future_text = data['ttf_future'].replace('<br>', '\n')
    return f"{data['place']}:\n{ttf_future_text}"


def build_email_for_user(user: dict) -> EmailMessage:
    # Lager eposten som brukererene får
    recipient_email = user["email"]
    favorites = user.get("favorites", [])

    # Create the body with fire risk forecasts for each favorite
    if favorites:
        body_parts = []
        for fav in favorites:
            lat = fav["lat"]
            lon = fav["lon"]
            ttf_data = get_weather_data_for_email(lat, lon)
            body_parts.append(ttf_data)
        body = "Hello,\n\nHere are your fire risk forecasts for favorited locations:\n\n" + \
            "\n\n".join(body_parts) + "\n\nBest regards,\nFireGuard"
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
    # Sender emailen
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
    hour=00,
    minute=5,
    id="daily_notification",
    name="Daily notification at midnight",
    replace_existing=True
)
scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())
# ---------------Sende Emails--------------------


def calculate_weather_data(lat, lon):
    # Denne brukes både når email skal lages og når kartet klikkes på
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"

    headers = {
        "User-Agent": "FireGuard/1.0 668523@stud.hvl.no" #I fremtiden, ta imot emailen til en bruker og bruk den istedenfor
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return None

    all_data = response.json()

    geo_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    geo_res = requests.get(geo_url, headers=headers).json()
    addr = geo_res.get("address", {})

    place = addr.get("suburb") or addr.get("village") or addr.get(
        "town") or addr.get("city") or "Unknown place"
    municipality = addr.get("municipality") or addr.get(
        "city") or "Unknown municipality"


    # --------------Fire risk-kalkulering--------------------
    #For å returnere værdata for i dag
    current = all_data["properties"]["timeseries"][0]["data"]["instant"]["details"]

    # --------------Fire risk-kalkulering--------------------
    timeseries = all_data["properties"]["timeseries"]

    weather_points = []

    for entry in timeseries:
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

    weatherData = frcm.WeatherData(data=weather_points)

    ttf_customClass = frcm.compute(weatherData)
    ttf_text = str(ttf_customClass)
    ttf_csv = pd.read_csv(io.StringIO(ttf_text), parse_dates=["timestamp"])

    # Current time to flashover
    first_timestamp_pd = ttf_csv["timestamp"].iloc[1]
    first_timestamp_string = first_timestamp_pd.strftime(
        "%d. %B, %H:%M").lower()
    first_ttf_float = float(ttf_csv["ttf"].iloc[1])

    # Future time to flashover
    ttf_future = ""
    for i in range(2, min(11, len(ttf_csv))):
        timestamp = ttf_csv["timestamp"].iloc[i]
        ttf_value = float(ttf_csv["ttf"].iloc[i])
        ttf_future += f"{timestamp.strftime('%d. %B, %H:%M').lower()} {ttf_value:.2f} min<br>"
    # ------------------------------------------------------

    return {
        "place": place,
        "municipality": municipality,
        "county": county,
        "temperature": current["air_temperature"],
        "wind_speed": current["wind_speed"],
        "humidity": current["relative_humidity"],
        "timestamp": first_timestamp_string,
        "ttf_current": first_ttf_float,
        "ttf_future": ttf_future
    }


@app.route("/weather")
def get_weather():
    lat = request.args.get("lat")
    lon = request.args.get("lon")

    if not lat or not lon:
        return jsonify({"error": "Missing coordinates"}), 400

    data = calculate_weather_data(lat, lon)

    if data is None:
        return jsonify({"error": "Failed to fetch weather"}), 500

    return jsonify({
        "place": data["place"],
        "county": data["county"],
        "temperature": data["temperature"],
        "wind_speed": data["wind_speed"],
        "humidity": data["humidity"],
        "timestamp": data["timestamp"],
        "ttf_current": f"{data['ttf_current']:.2f}",
        "ttf_future": data["ttf_future"]
    })


@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')

@app.route("/login")
def login():
    auth_url = keycloak_openid.auth_url(
        redirect_uri="http://158.39.75.130:8000/callback", #158.39.75.130
        scope="openid"
    )
    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")

    if not code:
        return "Missing authorization code", 400

    token = keycloak_openid.token(
        grant_type="authorization_code",
        code=code,
        redirect_uri="http://158.39.75.130:8000/callback" #158.39.75.130
    )
    print("TOKEN RESPONSE: ", token)

    userinfo = keycloak_openid.userinfo(token["access_token"])
    session["user"] = userinfo
    user_id = userinfo["sub"]
    bruker = db.session.get(Bruker, user_id)
    if not bruker:
        bruker = Bruker(
            keycloak_id=user_id,
            brukernavn=userinfo["preferred_username"],
            email=userinfo["email"]
        )
        db.session.add(bruker)
        db.session.commit()

    return redirect("/mainpage")

@app.route('/set-guest', methods=['POST'])
def set_guest():
    session['user'] = {"preferred_username": "Guest"}
    return '', 204


@app.route('/mainpage')
def mainpage():
    user = session.get("user")
    if not user:
        return redirect("/login")
    steder = Tettsted.query.all()
    places = [{
        "name": s.name,
        "lat": s.lat,
        "long": s.long
    }
    for s in steder]

    favorites = db.session.query(Tettsted).join(
        Favoritter, Favoritter.tettsted_id == Tettsted.id
    ).filter(
        Favoritter.bruker_id == session["keycloak_id"]
    ).all()

    return render_template('mainpage.html', places=places, favorites=favorites, username=user["preferred_username"])

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

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


# Database greier
@app.route("/favorite/<string::tettsted_name>/<string::kommune_name>/<string::fylke_name>", methods=["POST"])
def add_favorite(tettsted_name, kommune_name, fylke_name):
    user_id = session.get("keycloak_id")
    fylke = Fylke.query.select(Fylke).where(Fylke.name == fylke_name).first()
    kommune_id = Kommune.query.select(Kommune).where(Kommune.name == kommune_name, Kommune.fylke_name == fylke)
    tettsted = Tettsted.query.select(Tettsted).where(Tettsted.name == tettsted_name, Tettsted.kommune_id == kommune_id.id)

    fav = Favoritter (
        bruker_id = user_id,
        tettsted_id = tettsted.id
    )

    db.session.add(fav)
    db.session.commit()
    return "", 204

@app.route("/favorite/<int::tettsted>", methods=["DELETE"])
def remove_favorite(tettsted_id):
    user_id = session.get("keycloak_id")
    fav = Favoritter.query.filter_by(
        bruker_id = user_id,
        tettsted_id = tettsted_id
    ).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
    return "", 204