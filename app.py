import json
import os
import threading
from flask import Flask, render_template, jsonify, request
from scraper import scrape_city, CITY_LOCATIONS
from analyzer import analyze

app = Flask(__name__)

_scan_status = {"running": False, "progress": "", "done": False, "error": ""}
_last_analysis: dict = {}

DATA_FILE = "data_raw.json"


def _run_scan(city: str, keyword: str):
    global _last_analysis
    _scan_status.update({"running": True, "done": False, "error": "", "progress": f"Scanning {city}..."})
    try:
        data = scrape_city(city, max_restaurants=500, keyword=keyword)
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
        _last_analysis = analyze(data)
        _scan_status["progress"] = f"Complete — {len(data)} data points found."
        _scan_status["done"] = True
    except Exception as e:
        _scan_status["error"] = str(e)
        _scan_status["progress"] = f"Error: {e}"
    finally:
        _scan_status["running"] = False


@app.route("/")
def index():
    cities = list(CITY_LOCATIONS.keys())
    return render_template("index.html", cities=cities)


@app.route("/api/scan", methods=["POST"])
def api_scan():
    if _scan_status["running"]:
        return jsonify({"error": "Scan already in progress"}), 409
    body = request.get_json(silent=True) or {}
    city    = body.get("city", "philadelphia").lower()
    keyword = body.get("keyword", "avocado").lower()
    thread = threading.Thread(target=_run_scan, args=(city, keyword), daemon=True)
    thread.start()
    return jsonify({"status": "started", "city": city, "keyword": keyword})


@app.route("/api/status")
def api_status():
    return jsonify(_scan_status)


@app.route("/api/results")
def api_results():
    global _last_analysis
    if not _last_analysis:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE) as f:
                data = json.load(f)
            _last_analysis = analyze(data)
        else:
            return jsonify({"error": "No data yet. Run a scan first."}), 404

    safe = {k: v for k, v in _last_analysis.items() if k != "raw_addons"}
    return jsonify(safe)


@app.route("/api/raw")
def api_raw():
    if not os.path.exists(DATA_FILE):
        return jsonify([])
    with open(DATA_FILE) as f:
        return jsonify(json.load(f))


if __name__ == "__main__":
    print("Starting Avocado Price Tracker on http://localhost:5000")
    app.run(debug=True, port=5000)
