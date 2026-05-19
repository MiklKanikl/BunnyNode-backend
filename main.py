from flask import Flask, request, jsonify
import random

app = Flask(__name__)
data = {}

@app.route("/api/create_token/")
def create_token():
    t = 0
    while t == 0 or t in data.keys():
        t = random.randint(1000, 9999)

    data[t] = {"nodes": [], "edges": []}
    return str(t)

@app.route("/api/get_data/", methods=['Post'])
def get_data():
    t = request.args.get("key")
    if t in data.keys():
        return jsonify(data[t])
    else:
        return "key does not exist", 400

@app.route("/api/send_data/", methods=['Post'])
def send_data():
    c_request = request.get_json()
    c_data = c_request["data"]
    c_key = c_request["key"]
    data[c_key] = c_data
    return "success", 200

if __name__ == '__main__':
    app.run()