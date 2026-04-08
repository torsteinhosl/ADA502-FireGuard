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
    server_url="http://keycloak:8080/",
    client_id="fireguard-app",
    realm_name="fireguard",
    client_secret_key=None
)

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

@app.route("/weather")
def get_weather():
    lat = request.args.get("lat")
    lon = request.args.get("lon")

    if not lat or not lon:
        return jsonify({"error": "Missing coordinates"}), 400

    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"

    headers = {
        "User-Agent": "FireGuard/1.0 668523@stud.hvl.no" #I fremtiden, ta imot emailen til en bruker og bruk den istedenfor
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch weather"}), 500

    all_data = response.json()

    # -----Dette er her for testing---
    #path = "C:\\Users\\jonas\\Desktop\\test\\bergen_2026_01_09.json"
    #with open(path, "r", encoding="utf-8") as f:
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

    #Funksjon fra FRC for å få dataen på en form den kan kalkulere med
    weatherData = frcm.WeatherData(data=weather_points)

    # Time to flashover, i forskjellige formater som kan benyttes:
    ttf_customClass = frcm.compute(weatherData)     #Kalkulerer ttf og får ut en rar datatype
    ttf_text = str(ttf_customClass)                 #Gjør resultatetne om til en rein string
    ttf_csv = pd.read_csv(io.StringIO(ttf_text), parse_dates=["timestamp"]) #Gjør stringen om til en csv-fil for senere bruk

    # Blanding av ny og gammel kode. Tid og fire riske for nå-tid lages for seg selv, mens fremtidig tid kommer senere
    first_timestamp_pd = ttf_csv["timestamp"].iloc[1]
    first_timestamp_string = first_timestamp_pd.strftime("%d. %B, %H:%M").lower() 

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
    return render_template('index.html')

@app.route("/login")
def login():
    auth_url = keycloak_openid.auth_url(
        redirect_uri="http://localhost:8000/callback", #158.39.75.130
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
        redirect_uri="http://localhost:8000/callback" #158.39.75.130
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
    
    return render_template('mainpage.html', username=user["preferred_username"])

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)


# Database greier
@app.route("/fylker")
def get_fylker():
    fylker = Fylke.query.all()
    return [f.name for f in fylker]

@app.route("/add-tettsted")
def add_tettsted():
    new_tettsted = Tettsted(
        name="Salhus",
        kommune_id = 1,
    )
    db.session.add(new_tettsted)
    db.session.commit()
    return "Added"
