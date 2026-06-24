from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
import os

load_dotenv()

app = Flask(__name__)
CORS(app)

# ==========================
# MongoDB Connection
# ==========================



client = MongoClient(
    os.getenv("MONGO_URI")
)

db = client["AGRINEXUS"]

# ==========================
# Government API
# ==========================
API_KEY = os.getenv("API_KEY")

RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"

# ==========================
# AGMARKNET FETCHER
# ==========================
def fetch_agmarknet_prices():

    url = f"https://api.data.gov.in/resource/{RESOURCE_ID}"

    params = {
        "api-key": API_KEY,
        "format": "json",
        "limit": 10
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        print("Status:", response.status_code)

        if response.status_code != 200:
            return []

        data = response.json()

        return data.get(
            "records",
            []
        )

    except requests.exceptions.Timeout:

        print("AGMARKNET TIMEOUT")

        return []

    except Exception as e:

        print("AGMARKNET ERROR:", str(e))

        return []


# ==========================
# HOME
# ==========================
@app.route("/")
def home():
    return "AGRINEXUS Backend Running"


# ==========================
# HEALTH CHECK
# ==========================
@app.route("/api/health")
def health():
    return jsonify({
        "status": "online",
        "database": "connected"
    })


# ==========================
# AGMARKNET TEST
# ==========================
@app.route("/api/agmarknet-test")
def agmarknet_test():

    records = fetch_agmarknet_prices()

    return jsonify({
        "count": len(records),
        "records": records
    })


# ==========================
# AGMARKNET RAW RESPONSE
# ==========================
@app.route("/api/agmarknet-raw")
def agmarknet_raw():

    url = f"https://api.data.gov.in/resource/{RESOURCE_ID}"

    params = {
        "api-key": API_KEY,
        "format": "json",
        "limit": 5
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        return response.text

    except Exception as e:

        return jsonify({
            "status": "failed",
            "message": str(e)
        })


# ==========================
# MARKET PRICE
# ==========================
@app.route("/api/market-price")
def market_price():

    crop = request.args.get("crop")
    district = request.args.get("district")

    data = db.market_prices.find_one({
        "crop": crop,
        "district": district
    })

    if not data:
        return jsonify({})

    return jsonify({
        "crop": data["crop"],
        "district": data["district"],
        "market": data["market"],
        "modal_price": data["modal_price"],
        "min_price": data["min_price"],
        "max_price": data["max_price"],
        "unit": data["unit"]
    })


# ==========================
# STATES
# ==========================
@app.route("/api/states")
def get_states():

    states = list(db.states.find({}))

    return jsonify([
        {
            "id": state["_id"],
            "name": state["name"]
        }
        for state in states
    ])


# ==========================
# DISTRICTS
# ==========================
@app.route("/api/districts")
def get_districts():

    state_id = request.args.get("state_id")

    districts = list(
        db.districts.find({
            "state_id": state_id
        })
    )

    return jsonify([
        {
            "id": district["_id"],
            "name": district["name"]
        }
        for district in districts
    ])


# ==========================
# TALUKAS
# ==========================
@app.route("/api/talukas")
def get_talukas():

    district_id = request.args.get("district_id")

    talukas = list(
        db.talukas.find({
            "district_id": district_id
        })
    )

    return jsonify([
        {
            "id": taluka["_id"],
            "name": taluka["name"]
        }
        for taluka in talukas
    ])


# ==========================
# PADDY VARIETIES
# ==========================
@app.route("/api/crops/paddy")
def get_paddy_varieties():

    state_id = request.args.get("state_id")
    district_id = request.args.get("district_id")
    taluka_id = request.args.get("taluka_id")

    crops = list(
        db.paddy_varieties.find({
            "state_id": state_id,
            "district_id": district_id,
            "taluka_id": taluka_id
        })
    )

    result = []

    for crop in crops:

        crop["id"] = crop["_id"]

        if "_id" in crop:
            del crop["_id"]

        result.append(crop)

    return jsonify(result)


# ==========================
# DISEASE RISK ENGINE
# ==========================
@app.route("/api/disease-risk")
def disease_risk():

    humidity = float(
        request.args.get("humidity", 0)
    )

    temperature = float(
        request.args.get("temperature", 0)
    )

    diseases = list(
        db.disease_database.find({})
    )

    risks = []

    for disease in diseases:

        if (
            humidity >= disease.get("humidity_min", 0)
            and temperature >= disease.get("temperature_min", 0)
            and temperature <= disease.get("temperature_max", 100)
        ):

            risks.append({
                "name": disease.get("name", ""),
                "severity": disease.get("severity", "Medium"),
                "symptoms": disease.get("symptoms", []),
                "prevention": disease.get("prevention", [])
            })

    return jsonify(risks)


# ==========================
# MAIN
# ==========================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
