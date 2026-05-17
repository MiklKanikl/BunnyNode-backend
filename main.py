from flask import Flask, request
import random

app = Flask(__name__)
data = {}

@app.route("/api/create_token/")
def create_token():
    t = random.randint(1000, 9999)
    data[t] = {"nodes": [], "edges": []}
    return t

@app.route("/api/get_data/")
def get_data():
    t = request.args.get("key")
    return data[t]

@app.route("/api/send_data/")
def send_data():
    c_request = request.get_json()
    c_data = c_request["data"]
    c_key = c_request["key"]
    data[c_key] = c_data

if __name__ == '__main__':
    app.run()