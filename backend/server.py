from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import json
import os

# Setup Flask to serve static files from the frontend directory
frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../frontend')
app = Flask(__name__, static_folder=frontend_dir)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.sqlite')
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../api/config.json')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            lng REAL,
            lat REAL
        )
    ''')
    conn.commit()
    conn.close()

# Initialize the database on startup
init_db()

# --- Static File Routes ---

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(app.static_folder, path)

# --- API Routes ---

@app.route('/api/config', methods=['GET'])
def get_config():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config_data = json.load(f)
                return jsonify(config_data)
        else:
            return jsonify({"MAPBOX_KEY": "YOUR_MAPBOX_ACCESS_TOKEN_HERE"})
    except Exception as e:
        return jsonify({"error": "Failed to read config"}), 500

@app.route('/api/locations', methods=['GET', 'POST'])
def locations():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == 'GET':
        c.execute('SELECT * FROM locations')
        rows = c.fetchall()
        conn.close()
        return jsonify([dict(row) for row in rows])

    if request.method == 'POST':
        data = request.json
        name = data.get('name')
        lng = data.get('lng')
        lat = data.get('lat')

        if not name or lng is None or lat is None:
            conn.close()
            return jsonify({"error": "Please provide name, lng, and lat"}), 400

        c.execute('INSERT INTO locations (name, lng, lat) VALUES (?, ?, ?)', (name, lng, lat))
        conn.commit()
        last_id = c.lastrowid
        conn.close()
        return jsonify({"id": last_id, "name": name, "lng": lng, "lat": lat})

@app.route('/api/locations/<int:loc_id>', methods=['DELETE'])
def delete_location(loc_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM locations WHERE id = ?', (loc_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

if __name__ == '__main__':
    print("Starting Flask server on http://localhost:3000")
    app.run(host='0.0.0.0', port=3000)
