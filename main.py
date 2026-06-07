from flask import Flask, request, jsonify
import random
import json
import copy

app = Flask(__name__)
data = {}
@app.route("/")
def index():
    return "BunnyNode Backend is running"

@app.route("/api/create_token/")
def create_token():
    t = 0
    while t == 0 or t in data.keys():
        t = random.randint(1000, 9999)

    data[t] = {
        "nodes": [], 
        "edges": [],
        "version": 0,
        "node_index": {},
        "edge_index": {}
    }
    return str(t)

@app.route("/api/get_data/", methods=['GET', 'POST'])
def get_data():
    if request.method == 'POST' and request.is_json:
        t = request.get_json().get("key")
    else:
        t = request.args.get("key")
    
    try:
        t = int(t)
    except (ValueError, TypeError):
        return "Invalid key format", 400
    
    if t in data.keys():
        return jsonify({
            "version": data[t]["version"],
            "nodes": data[t]["nodes"],
            "edges": data[t]["edges"]
        })
    else:
        return "key does not exist", 400

@app.route("/api/send_delta/", methods=['POST'])
def send_delta():
    try:
        c_request = request.get_json()
        c_key = int(c_request["key"])
        base_version = c_request.get("base_version", 0)
        changes = c_request.get("changes", {})
        
        if c_key not in data:
            return "Scene not found", 404
        
        current_version = data[c_key]["version"]
        if base_version != current_version:
            return jsonify({
                "status": "conflict",
                "message": f"Version mismatch. Your version: {base_version}, Server version: {current_version}",
                "server_version": current_version,
                "conflict": True
            }), 409
        
        apply_delta(c_key, changes)
        
        data[c_key]["version"] += 1
        
        return jsonify({
            "status": "success",
            "new_version": data[c_key]["version"]
        }), 200
        
    except Exception as e:
        return f"Error: {str(e)}", 400

def apply_delta(scene_key, changes):
    """Apply delta changes to the scene"""
    scene = data[scene_key]
    
    if "nodes_added" in changes:
        for node in changes["nodes_added"]:
            scene["nodes"].append(node)
            scene["node_index"][node["id"]] = node
    
    if "nodes_modified" in changes:
        for node_update in changes["nodes_modified"]:
            node_id = node_update["id"]
            if node_id in scene["node_index"]:
                scene["node_index"][node_id].update(node_update)
            else:
                scene["nodes"].append(node_update)
                scene["node_index"][node_id] = node_update
    
    if "nodes_removed" in changes:
        for node_id in changes["nodes_removed"]:
            if node_id in scene["node_index"]:
                node = scene["node_index"][node_id]
                scene["nodes"].remove(node)
                del scene["node_index"][node_id]
    
    if "edges_added" in changes:
        for edge in changes["edges_added"]:
            scene["edges"].append(edge)
            scene["edge_index"][edge.get("id")] = edge
    
    if "edges_modified" in changes:
        for edge_update in changes["edges_modified"]:
            edge_id = edge_update.get("id")
            if edge_id in scene["edge_index"]:
                scene["edge_index"][edge_id].update(edge_update)
    
    if "edges_removed" in changes:
        for edge_id in changes["edges_removed"]:
            if edge_id in scene["edge_index"]:
                edge = scene["edge_index"][edge_id]
                scene["edges"].remove(edge)
                del scene["edge_index"][edge_id]

@app.route("/api/get_changes_since/", methods=['GET'])
def get_changes_since():
    t = request.args.get("key")
    since_version = request.args.get("version", 0)
    
    try:
        t = int(t)
        since_version = int(since_version)
    except (ValueError, TypeError):
        return "Invalid parameters", 400
    
    if t not in data:
        return "Scene not found", 404
    
    if data[t]["version"] > since_version:
        return jsonify({
            "version": data[t]["version"],
            "full_update": True,
            "nodes": data[t]["nodes"],
            "edges": data[t]["edges"]
        })
    else:
        return jsonify({
            "version": data[t]["version"],
            "full_update": False,
            "message": "Already up to date"
        })

@app.route("/api/send_data/", methods=['POST'])
def send_data():
    try:
        c_request = request.get_json()
        c_data = c_request["data"]
        c_key = int(c_request["key"])
        
        data[c_key] = {
            "nodes": c_data.get("nodes", []),
            "edges": c_data.get("edges", []),
            "version": data.get(c_key, {}).get("version", 0) + 1,
            "node_index": {},
            "edge_index": {}
        }
        
        for node in data[c_key]["nodes"]:
            data[c_key]["node_index"][node["id"]] = node
        
        for edge in data[c_key]["edges"]:
            data[c_key]["edge_index"][edge.get("id")] = edge
        
        return "success", 200
        
    except Exception as e:
        return f"Error: {str(e)}", 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)