from flask import Flask, jsonify, request
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, auth
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from bson import ObjectId
from bson.errors import InvalidId
import os
from datetime import datetime

# ==========================
# ENV SETUP
# ==========================
# IMPORTANT: the project's env file is named "variable.env", not ".env",
# so it must be passed explicitly or load_dotenv() will silently find nothing.
load_dotenv("variable.env")

MONGO_URI = os.getenv("MONGO_URI")
API_KEY = os.getenv("API_KEY")
FIREBASE_CRED_PATH = os.getenv("FIREBASE_CRED_PATH", "firebase/serviceAccountKey.json")

if not MONGO_URI:
    raise RuntimeError(
        "MONGO_URI is not set. Add it to variable.env (MONGO_URI=...) "
        "or as an environment variable before starting the app."
    )

# ==========================
# FIREBASE INIT
# ==========================
cred = credentials.Certificate(FIREBASE_CRED_PATH)
firebase_admin.initialize_app(cred)

app = Flask(__name__)
CORS(app)

# ==========================
# MongoDB Connection
# ==========================
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["AGRINEXUS"]
users = db.users

# ==========================
# Government API
# ==========================
RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"


# ==========================
# HELPERS
# ==========================
def serialize_doc(doc):
    """Convert a Mongo document's ObjectId fields into strings so jsonify works."""
    if doc is None:
        return None
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc[key] = str(value)
    return doc


def to_object_id(value):
    """Safely convert a string to ObjectId, returns None if invalid."""
    if not value:
        return None
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def verify_token(req):
    """Verify the Firebase ID token from the Authorization header.
    Returns (decoded_token, error_response_or_None)."""
    token = req.headers.get("Authorization")

    if not token:
        return None, (jsonify({
            "success": False,
            "message": "Authorization token missing"
        }), 401)

    token = token.replace("Bearer ", "").strip()

    try:
        decoded = auth.verify_id_token(token)
        return decoded, None
    except Exception as e:
        print("TOKEN VERIFY ERROR:", e)
        return None, (jsonify({
            "success": False,
            "message": "Invalid or expired token"
        }), 401)


# ==========================
# AGMARKNET FETCHER
# ==========================
def fetch_agmarknet_prices():
    if not API_KEY:
        print("AGMARKNET: API_KEY not configured")
        return []

    url = f"https://api.data.gov.in/resource/{RESOURCE_ID}"
    params = {
        "api-key": API_KEY,
        "format": "json",
        "limit": 10
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        print("Status:", response.status_code)

        if response.status_code != 200:
            return []

        data = response.json()
        return data.get("records", [])

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
    db_status = "connected"
    try:
        client.admin.command("ping")
    except PyMongoError as e:
        print("DB HEALTH CHECK FAILED:", e)
        db_status = "disconnected"

    return jsonify({
        "status": "online",
        "database": db_status
    })
@app.route("/routes")
def routes():
    return {
        "routes": sorted([str(rule) for rule in app.url_map.iter_rules()])
    }

# ==========================
# REGISTER
# ==========================
@app.route("/api/register", methods=["POST"])
def register():
    print("\n========== REGISTER API HIT ==========")

    decoded, error = verify_token(request)
    if error:
        return error

    uid = decoded["uid"]
    phone = decoded.get("phone_number", "")

    print("Firebase UID :", uid)
    print("Phone        :", phone)

    data = request.get_json(silent=True) or {}
    print("REQUEST DATA :", data)

    required_fields = ["name", "role"]
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        return jsonify({
            "success": False,
            "message": f"Missing required fields: {', '.join(missing)}"
        }), 400

    try:
        existing = users.find_one({
            "$or": [
                {"firebase_uid": uid},
                {"phone": phone}
            ]
        })

        if existing:
            print("USER ALREADY EXISTS")
            return jsonify({
                "success": False,
                "message": "User already registered"
            }), 409

        user = {
            "firebase_uid": uid,
            "phone": phone,
            "name": data.get("name"),
            "role": data.get("role"),
            "village": data.get("village"),
            "taluk": data.get("taluk"),
            "district": data.get("district"),
            "pincode": data.get("pincode"),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "is_active": True
        }

        print("INSERTING USER...")
        users.insert_one(user)
        print("USER INSERTED SUCCESSFULLY")

        return jsonify({
            "success": True,
            "message": "Registration Successful"
        }), 200

    except PyMongoError as e:
        print("DATABASE ERROR (register):", e)
        return jsonify({
            "success": False,
            "message": "Database error. Please try again later."
        }), 500


# ==========================
# LOGIN
# ==========================
@app.route("/api/login", methods=["POST"])
def login():
    print("\n========== LOGIN API HIT ==========")

    decoded, error = verify_token(request)
    if error:
        return error

    uid = decoded["uid"]
    print("Firebase UID :", uid)

    try:
        user = users.find_one({"firebase_uid": uid})
    except PyMongoError as e:
        print("DATABASE ERROR (login):", e)
        return jsonify({
            "success": False,
            "message": "Database error. Please try again later."
        }), 500

    if user is None:
        print("USER NOT REGISTERED")
        return jsonify({
            "success": True,
            "registered": False
        })

    print("LOGIN SUCCESS")
    return jsonify({
        "success": True,
        "registered": True,
        "firebase_uid": user["firebase_uid"],
        "phone": user["phone"],
        "name": user["name"],
        "role": user["role"],
        "village": user.get("village"),
        "taluk": user.get("taluk"),
        "district": user.get("district"),
        "pincode": user.get("pincode")
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
        response = requests.get(url, params=params, timeout=30)
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
        "crop": data.get("crop"),
        "district": data.get("district"),
        "market": data.get("market"),
        "modal_price": data.get("modal_price"),
        "min_price": data.get("min_price"),
        "max_price": data.get("max_price"),
        "unit": data.get("unit")
    })


# ==========================
# STATES
# ==========================
@app.route("/api/states")
def get_states():
    states = list(db.states.find({}))
    return jsonify([serialize_doc(state) for state in states])


# ==========================
# DISTRICTS
# ==========================
@app.route("/api/districts")
def get_districts():
    state_id = to_object_id(request.args.get("state_id"))

    if state_id is None:
        return jsonify({
            "success": False,
            "message": "Valid state_id is required"
        }), 400

    districts = list(db.districts.find({"state_id": state_id}))
    return jsonify([serialize_doc(d) for d in districts])


# ==========================
# TALUKAS
# ==========================
@app.route("/api/talukas")
def get_talukas():
    district_id = to_object_id(request.args.get("district_id"))

    if district_id is None:
        return jsonify({
            "success": False,
            "message": "Valid district_id is required"
        }), 400

    talukas = list(db.talukas.find({"district_id": district_id}))
    return jsonify([serialize_doc(t) for t in talukas])


# ==========================
# PADDY VARIETIES
# ==========================
@app.route("/api/crops/paddy")
def get_paddy_varieties():
    state_id = to_object_id(request.args.get("state_id"))
    district_id = to_object_id(request.args.get("district_id"))
    taluka_id = to_object_id(request.args.get("taluka_id"))

    query = {}
    if state_id:
        query["state_id"] = state_id
    if district_id:
        query["district_id"] = district_id
    if taluka_id:
        query["taluka_id"] = taluka_id

    crops = list(db.paddy_varieties.find(query))
    return jsonify([serialize_doc(c) for c in crops])


# ==========================
# DISEASE RISK ENGINE
# ==========================
@app.route("/api/disease-risk")
def disease_risk():
    try:
        humidity = float(request.args.get("humidity", 0))
        temperature = float(request.args.get("temperature", 0))
    except ValueError:
        return jsonify({
            "success": False,
            "message": "humidity and temperature must be numbers"
        }), 400

    diseases = list(db.disease_database.find({}))
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
# ERROR HANDLERS
# ==========================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"success": False, "message": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"success": False, "message": "Internal server error"}), 500


# ==========================
# MAIN
# ==========================
if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=debug_mode
    )
