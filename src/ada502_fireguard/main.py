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

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Variables
VALID_USERNAME = 'test'
VALID_PASSWORD = 'test'

m = folium.Map(location=[62.972077, 10.395563], zoom_start=6)


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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
