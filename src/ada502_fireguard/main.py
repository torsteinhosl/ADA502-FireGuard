from dotenv import load_dotenv
import os   # Dette har med sikker lagring av passord til fireguard email
from email.message import EmailMessage
import smtplib
from datetime import datetime, time as dt_time, timezone
import atexit
from apscheduler.schedulers.background import BackgroundScheduler  # For å trigge emails
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
import time
from datetime import date

keycloak_openid = KeycloakOpenID(
    server_url="http://keycloak:8080/",  # 158.39.75.130
    client_id="fireguard-app",
    realm_name="fireguard",
    client_secret_key=None
)

# Load environment variables
load_dotenv()

app = Flask(__name__)

app.secret_key = "supersecretkey"

app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False
)

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
    kommune_id = db.Column(db.Integer, db.ForeignKey("kommune.id"))
    latitude = db.Column(db.Double)
    longitude = db.Column(db.Double)


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


class HistoriskData(db.Model):
    __tablename__ = "historiskdata"
    id = db.Column(db.Integer, primary_key=True)
    tettsted_id = db.Column(db.Integer, db.ForeignKey("tettsted.id"))
    dato = db.Column(db.Date)
    temperatur = db.Column(db.Float)
    vind = db.Column(db.Float)
    luftfuktighet = db.Column(db.Float)
    firerisk = db.Column(db.Float)


@app.before_request
def debug_request():
    print("HOST:", request.host)
    print("PATH:", request.path)


# ---------------Sende Emails--------------------
# Example users used to create emails, will be changed later det er snart
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


def save_midday_weather():
    with app.app_context():
        tettsteder = db.session.query(
            Tettsted.id, Tettsted.latitude, Tettsted.longitude).all()
        today = date.today()

        for t in tettsteder:
            time.sleep(5)
            data = calculate_weather_data(t.latitude, t.longitude)
            if not data:
                continue

            for entry in data["forecast"]:
                timestamp = parser.isoparse(entry["time"])
                if timestamp.hour != 12 or timestamp.date() != today:
                    continue

                dato = timestamp.date()
                existing = HistoriskData.query.filter_by(
                    tettsted_id=t.id,
                    dato=dato
                ).first()
                if existing:
                    continue

                record = HistoriskData(
                    tettsted_id=t.id,
                    dato=dato,
                    temperatur=entry["temperature"],
                    vind=entry["wind_speed"],
                    luftfuktighet=entry["humidity"],
                    firerisk=entry["ttf"]
                )
                db.session.add(record)
        db.session.commit()
        return "Recorded weather data", 204


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
scheduler.add_job(
    func=save_midday_weather,
    trigger="cron",
    hour=0,
    minute=10,
    id="save_midday_weather",
    name="Saving midday weather",
    replace_existing=True
)
scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())
# ---------------Sende Emails--------------------


def calculate_weather_data(lat, lon):
    # Denne brukes både når email skal lages og når kartet klikkes på

    # --------------Hente data fra MET om fremtidig vær-----------
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"

    headers = {
        # I fremtiden, ta imot emailen til en bruker og bruk den istedenfor
        "User-Agent": "FireGuard/1.0 668523@stud.hvl.no"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return None

    all_data_future = response.json()

    geo_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    geo_res = requests.get(geo_url, headers=headers).json()
    addr = geo_res.get("address", {})

    place = addr.get("suburb") or addr.get("village") or addr.get(
        "town") or addr.get("city") or "Unknown place"
    municipality = addr.get("municipality") or addr.get(
        "city") or "Unknown municipality"
    county = addr.get("county")

    # ------------Hente data fra database med historiske værdata--------
    # Sjekker ført om det valgte stedet har historiske væredata å gå utifra
    place_weatherdata_past = Tettsted.query.filter_by(
        latitude=lat, longitude=lon).first()
    if place_weatherdata_past:
        weatherdata_past = db.session.query(HistoriskData.temperatur, HistoriskData.luftfuktighet,
                                            HistoriskData.vind, HistoriskData.dato).filter_by(tettsted_id=place_weatherdata_past.id).all()
    else:
        weatherdata_past = []

    # --------------Fire risk-kalkulering--------------------
    # Kun data for i dag (hører til gammel kode, brukes bare én gang og burde egentlig oppdateres):
    current = all_data_future["properties"]["timeseries"][0]["data"]["instant"]["details"]

    # Data for fremtiden:
    # Kun tidspunktene fra værdataen
    timeseries_future = all_data_future["properties"]["timeseries"]
    weather_points = []  # Tom liste som skal fylles med værdata

    # Lagrer både fortidig og fremtidig værdata i listen
    for temp, hum, wind, dato in weatherdata_past:
        timestamp = datetime.combine(dato, dt_time(12, 0), tzinfo=timezone.utc)
        weather_points.append(
            frcm.WeatherDataPoint(
                temperature=temp,
                humidity=hum,
                wind_speed=wind,
                timestamp=timestamp
            )
        )

    for entry in timeseries_future:
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

    print(ttf_csv)  # Denne er her for testing lol

    # Calculate how many historic data points were added
    historic_count = len(weatherdata_past)

    # Current time to flashover - use same logic as forecast
    first_timestamp_pd = ttf_csv["timestamp"].iloc[historic_count + 1]
    first_timestamp_string = first_timestamp_pd.strftime(
        "%d. %B, %H:%M").lower()
    first_ttf_float = float(ttf_csv["ttf"].iloc[historic_count + 1])

    # Future time to flashover
    forecast = []

    # Only iterate through the timeseries_future entries
    for i in range(1, len(timeseries_future)):
        # Adjust index to account for historic data in ttf_csv
        ttf_index = historic_count + i

        if ttf_index < len(ttf_csv):
            ttf_value = float(ttf_csv["ttf"].iloc[ttf_index])

            entry = timeseries_future[i]["data"]["instant"]["details"]
            # Use the timestamp directly from the API response
            timestamp = parser.isoparse(timeseries_future[i]["time"])

            forecast.append({
                "time": timestamp.isoformat(),
                "temperature": entry["air_temperature"],
                "wind_speed": entry["wind_speed"],
                "humidity": entry["relative_humidity"],
                "ttf": round(ttf_value, 2)
            })

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
        "forecast": forecast
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
        "municipality": data["municipality"],
        "county": data["county"],
        "temperature": data["temperature"],
        "wind_speed": data["wind_speed"],
        "humidity": data["humidity"],
        "timestamp": data["timestamp"],
        "ttf_current": f"{data['ttf_current']:.2f}",
        "forecast": data["forecast"]
    })


@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')


@app.route("/login")
def login():
    auth_url = keycloak_openid.auth_url(
        redirect_uri="http://158.39.75.130:8000/callback",  # 158.39.75.130
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
        redirect_uri="http://158.39.75.130:8000/callback"  # 158.39.75.130
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
    user = session["user"]
    if not user:
        return redirect("/login")
    steder = db.session.query(Tettsted.name, Kommune.name.label(
        "kommune"), Tettsted.latitude, Tettsted.longitude).join(Kommune).order_by(Tettsted.name.asc()).all()
    places = [{
        "name": s.name,
        "kommune": s.kommune,
        "lat": s.latitude,
        "long": s.longitude
    }
        for s in steder]

    user_id = user.get("sub")
    if user_id:
        favorites = db.session.query(Tettsted).join(
            Favoritter, Favoritter.tettsted_id == Tettsted.id
        ).filter(
            Favoritter.bruker_id == user_id
        ).all()
    else:
        favorites = []

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

# Database greier


@app.route("/favorite", methods=["POST"])
def add_favorite():
    data = request.get_json()
    if not data:
        return "No JSON received", 400

    tettsted = data.get("tettsted")
    kommune = data.get("kommune")
    fylke = data.get("fylke")

    userinfo = session.get("user")
    if not userinfo:
        return "Missing user", 401
    user_id = userinfo.get("sub")
    if not user_id:
        return "Invalid session, no sub", 401
    fylket = Fylke.query.filter_by(name=fylke).first()
    if not fylket:
        return "ingen fylke med navn " + fylke, 404
    kommunen = Kommune.query.filter_by(
        name=kommune, fylke_name=fylket.name).first()
    if not kommunen:
        new_kommune(kommune, fylke)
    kommunen = Kommune.query.filter_by(
        name=kommune, fylke_name=fylket.name).first()
    tettstedet = Tettsted.query.filter_by(
        name=tettsted, kommune_id=kommunen.id).first()
    if not tettstedet:
        new_tettsted(tettsted, kommunen.id, data.get("lat"), data.get("long"))
    tettstedet = Tettsted.query.filter_by(
        name=tettsted, kommune_id=kommunen.id).first()

    fav = Favoritter(
        bruker_id=user_id,
        tettsted_id=tettstedet.id
    )

    db.session.add(fav)
    db.session.commit()
    return "", 204


@app.route("/unfavorite", methods=["POST"])
def unfavorite():
    data = request.get_json()
    tettsted = data.get("tettsted")
    kommune = data.get("kommune")
    fylke = data.get("fylke")
    userinfo = session.get("user")
    user_id = userinfo.get("sub")
    if not user_id:
        return "Invalid session, no sub", 401
    fylket = Fylke.query.filter_by(name=fylke).first()
    kommunen = Kommune.query.filter_by(
        name=kommune, fylke_name=fylket.name).first()
    tettstedet = Tettsted.query.filter_by(
        name=tettsted, kommune_id=kommunen.id).first()

    favoritten = Favoritter.query.filter_by(
        bruker_id=user_id, tettsted_id=tettstedet.id).first()
    if not favoritten:
        return "Stedet er ikke favorittet", 400
    db.session.delete(favoritten)
    db.session.commit()

    return "", 204


@app.route("/nytt-sted", methods=["POST"])
def nytt_sted():
    data = request.get_json()

    tettsted_name = data.get("tettsted")
    kommune_name = data.get("kommune")
    fylke_name = data.get("fylke")
    lat = data.get("lat")
    long = data.get("long")

    if not all([tettsted_name, kommune_name, fylke_name, lat, long]):
        return "Missing data", 400

    fylket = Fylke.query.filter_by(name=fylke_name).first()
    if not fylket:
        return "ingen fylke med navn " + fylke_name, 404

    kommunen = Kommune.query.filter_by(
        name=kommune_name, fylke_name=fylket.name).first()
    if not kommunen:
        new_kommune(kommune_name, fylke_name)
        kommunen = Kommune.query.filter_by(
            name=kommune_name, fylke_name=fylket.name).first()

    tettstedet = Tettsted.query.filter_by(
        name=tettsted_name, kommune_id=kommunen.id).first()
    if not tettstedet:
        new_tettsted(tettsted_name, kommunen.id, lat, long)
    return jsonify({"status": "ok"})


@app.route("/history_dates")
def history_dates():
    lat = request.args.get("lat")
    long = request.args.get("long")

    tettsted = Tettsted.query.filter_by(latitude=lat, longitude=long).first()

    if not tettsted:
        return jsonify([])

    rows = HistoriskData.query.filter_by(
        tettsted_id=tettsted.id).order_by(HistoriskData.dato.desc()).all()

    return jsonify([{
        "date": r.dato.isoformat(),
        "temp": r.temperatur,
        "wind": r.vind,
        "humidity": r.luftfuktighet,
        "firerisk": r.firerisk
    }
        for r in rows
    ])


@app.route("/save_the_day")
def save_the_day():
    return save_midday_weather()


def new_kommune(kommune_navn, fylke):
    kommun = Kommune(
        name=kommune_navn,
        fylke_name=fylke
    )
    db.session.add(kommun)
    db.session.commit()
    return


def new_tettsted(tettsted_navn, kommune_id, lat, long):
    tettsted = Tettsted(
        name=tettsted_navn,
        kommune_id=kommune_id,
        latitude=lat,
        longitude=long
    )
    db.session.add(tettsted)
    db.session.commit()
    return


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
