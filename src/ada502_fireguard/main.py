import requests
from flask import Flask, render_template, jsonify, request, url_for, session
import folium
import frcm  # Dette er fire risk-kalkulatoren fra Lars
import datetime  # Trennger denne for firersikkalkulator
import pandas as pd
import io
import csv

app  = Flask(__name__)
app.secret_key = "supersecretkey"

#Variables
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

    data = response.json()

    current = data["properties"]["timeseries"][0]["data"]["instant"]["details"]

    geo_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    geo_res = requests.get(geo_url, headers=headers).json()
    addr = geo_res.get("address", {})

    place = addr.get("suburb") or addr.get("village") or addr.get("town") or addr.get("city") or "Unknown place"
    county = addr.get("municipality") or addr.get("city") or "Unknown municipality"

    # Fire risk-kalkulering:
    # Den trenger minst to tidspunkt av en eller annen grunnn. Bruker bare now-verdien videre
    now = datetime.datetime.now()
    wd = frcm.WeatherData(data=[
        frcm.WeatherDataPoint(
            temperature=float(current["air_temperature"]),
            humidity=float(current["relative_humidity"]),
            wind_speed=float(current["wind_speed"]),
            timestamp=now - datetime.timedelta(hours=1)  # Previous point
        ),
        frcm.WeatherDataPoint(
            temperature=float(current["air_temperature"]),
            humidity=float(current["relative_humidity"]),
            wind_speed=float(current["wind_speed"]),
            timestamp=now  # current point
        )
    ])
    # Har testet opp mot resultatene man får når man kjører "uv run python src/frcm/__main__.py ./bergen_2026_01_09.csv"
    # (skrev manuelt inn de to første linjene fra CSV-filen), og det ser ut til å stemme.

    # Time to flashover, i forskjellige formater:
    ttf_customClass = frcm.compute(wd)
    ttf_text = str(ttf_customClass)
    ttf_csv = pd.read_csv(io.StringIO(ttf_text), parse_dates=["timestamp"])

    # Verdiene som skal returneres og vises:
    last_timestamp_pd = ttf_csv["timestamp"].iloc[-1]
    last_timestamp_string = last_timestamp_pd.strftime("%d. %B, %H:%M").lower()
    last_ttf_float = float(ttf_csv["ttf"].iloc[-1])

    return jsonify({
        "place": place,
        "county": county,
        "temperature": current["air_temperature"],
        "wind_speed": current["wind_speed"],
        "humidity": current["relative_humidity"],
        "timestamp": last_timestamp_string,
        "ttf": f"{last_ttf_float:.2f}"
    })


@app.route('/', methods=['GET', 'POST'])
def index():

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if username == VALID_USERNAME and password == VALID_PASSWORD:
            session['username'] = username
            return jsonify({"success": True, "message": "Login successful"})
        else :
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
