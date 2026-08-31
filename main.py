import json
import logging
import random
import sys
import threading
import uuid
from datetime import datetime

from flask import Flask, jsonify, render_template, request
from flask_sock import Sock

logging.basicConfig(
    format="%(asctime)s %(message)s",
    level=logging.DEBUG,
)

app = Flask(__name__)
sock = Sock(app)

rooms = {}
active_sessions = {}
room_clients = {}
websocket_clients = {}
websocket_send_locks = {}
state_lock = threading.RLock()

def create_session(room_key, user_info=None):
    with state_lock:
        session_id = str(uuid.uuid4())
        active_sessions[session_id] = {
            'room': room_key,
            'last_activity': datetime.now().isoformat(),
            'user_info': user_info or {'name': f'User_{random.randint(100,999)}'}
        }
        if room_key not in room_clients:
            room_clients[room_key] = set()
        room_clients[room_key].add(session_id)
    return session_id

def remove_session(session_id):
    with state_lock:
        session = active_sessions.pop(session_id, None)
        if session is None:
            return None

        room = session['room']
        if room in room_clients:
            room_clients[room].discard(session_id)
            if not room_clients[room]:
                del room_clients[room]
        websocket_clients.pop(session_id, None)
        websocket_send_locks.pop(session_id, None)
        return session

def apply_delta(scene_key, changes):
    scene = rooms[scene_key]
    
    if changes["type"] == "nodes_added":
        for node in changes["nodes"]:
            scene["nodes"].append(node)
            scene["node_index"][node["id"]] = node
    
    if changes["type"] == "nodes_modified":
        for node_update in changes["nodes"]:
            node_id = node_update["id"]
            if node_id in scene["node_index"]:
                scene["node_index"][node_id].update(node_update)
    
    if changes["type"] == "nodes_and_edges_removed":
        for node_update in changes["nodes"]:
            node_id = node_update["id"]
            if node_id in scene["node_index"]:
                node = scene["node_index"][node_id]
                del scene["nodes"][scene["nodes"].index(node)]
                del scene["node_index"][node_id]
        
        for edge_update in changes["edges"]:
            edge_id = edge_update["id"]
            if edge_id in scene["edge_index"]:
                edge = scene["edge_index"][edge_id]
                del scene["edges"][scene["edges"].index(edge)]
                del scene["edge_index"][edge_id]
    
    if changes["type"] == "edges_added":
        for edge in changes["edges"]:
            scene["edges"].append(edge)
            scene["edge_index"][edge.get("id")] = edge
    
    if changes["type"] == "edges_modified":
        for edge_update in changes["edges"]:
            edge_id = edge_update.get("id")
            if edge_id in scene["edge_index"]:
                scene["edge_index"][edge_id].update(edge_update)

    if changes["type"] == "nodes_and_edges_added":
        for node in changes["nodes"]:
            scene["nodes"].append(node)
            scene["node_index"][node["id"]] = node
        
        for edge in changes["edges"]:
            scene["edges"].append(edge)
            scene["edge_index"][edge.get("id")] = edge
    
    rooms[scene_key] = scene

def send_message(websocket, message, send_lock=None):
    payload = json.dumps(message)
    if send_lock is None:
        websocket.send(payload)
        return

    with send_lock:
        websocket.send(payload)

def broadcast_to_room(room_key, message, exclude_sid=None):
    payload = json.dumps(message)
    with state_lock:
        clients = [
            (sid, websocket_clients.get(sid), websocket_send_locks.get(sid))
            for sid in room_clients.get(room_key, set())
            if sid != exclude_sid
        ]

    for sid, websocket, send_lock in clients:
        if websocket is None or send_lock is None:
            continue
        try:
            with send_lock:
                websocket.send(payload)
        except Exception as error:
            print(f"Could not send websocket message to {sid}: {error}")

@sock.route('/ws')
def websocket_handler(websocket):
    session_id = None
    room = None
    send_lock = threading.Lock()
    
    try:
        raw_msg = websocket.receive()
        if raw_msg is None:
            return

        try:
            msg = json.loads(raw_msg)
        except (json.JSONDecodeError, TypeError):
            send_message(websocket, {
                'type': 'error',
                'message': 'Invalid JSON'
            }, send_lock)
            return

        if not isinstance(msg, dict) or msg.get('type') != 'join':
            send_message(websocket, {
                'type': 'error',
                'message': 'First message must be a join request'
            }, send_lock)
            return

        try:
            room_key = int(msg.get('room'))
        except (TypeError, ValueError):
            send_message(websocket, {
                'type': 'error',
                'message': 'Invalid room'
            }, send_lock)
            return

        user_info = msg.get('user_info') or {}

        # Holding this client's send lock while registering guarantees that the
        # joined snapshot is delivered before any broadcast from another thread.
        with send_lock:
            with state_lock:
                if room_key not in rooms:
                    websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'Room not found'
                    }))
                    return

                session_id = create_session(room_key, user_info)
                websocket_clients[session_id] = websocket
                websocket_send_locks[session_id] = send_lock
                room = room_key
                joined_message = json.dumps({
                    'type': 'joined',
                    'session_id': session_id,
                    'room': room_key,
                    'version': rooms[room_key]['version'],
                    'nodes': rooms[room_key]['nodes'],
                    'edges': rooms[room_key]['edges']
                })
                joined_user_info = active_sessions[session_id]['user_info']
                total_clients = len(room_clients.get(room_key, set()))

            websocket.send(joined_message)

        broadcast_to_room(room_key, {
            'type': 'user_joined',
            'session_id': session_id,
            'user_info': joined_user_info,
            'total_clients': total_clients
        })

        while True:
            raw_msg = websocket.receive()
            if raw_msg is None:
                break

            try:
                msg = json.loads(raw_msg)
            except (json.JSONDecodeError, TypeError):
                send_message(websocket, {
                    'type': 'error',
                    'message': 'Invalid JSON'
                }, send_lock)
                continue

            if not isinstance(msg, dict):
                send_message(websocket, {
                    'type': 'error',
                    'message': 'Message must be a JSON object'
                }, send_lock)
                continue

            msg_type = msg.get('type')

            if msg_type == 'scene_change':
                changes = msg.get('changes')
                version = msg.get('version')

                with state_lock:
                    if room not in rooms:
                        continue

                    if version != rooms[room]['version']:
                        conflict_version = rooms[room]['version']
                        new_version = None
                    else:
                        apply_delta(room, changes)
                        rooms[room]['version'] += 1
                        rooms[room]['last_modified'] = datetime.now().isoformat()
                        active_sessions[session_id]['last_activity'] = datetime.now().isoformat()
                        conflict_version = None
                        new_version = rooms[room]['version']

                if conflict_version is not None:
                    send_message(websocket, {
                        'type': 'conflict',
                        'server_version': conflict_version
                    }, send_lock)
                    continue

                broadcast_to_room(room, {
                    'type': 'scene_update',
                    'changes': changes,
                    'version': new_version,
                    'updated_by': session_id
                }, exclude_sid=session_id)

                send_message(websocket, {
                    'type': 'update_success',
                    'new_version': new_version
                }, send_lock)

            elif msg_type == 'ping':
                with state_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]['last_activity'] = datetime.now().isoformat()
                send_message(websocket, {'type': 'pong'}, send_lock)

            elif msg_type == 'leave':
                break
    finally:
        if session_id:
            session = remove_session(session_id)
            if room and session:
                broadcast_to_room(room, {
                    'type': 'user_left',
                    'session_id': session_id,
                    'user_info': session.get('user_info')
                })

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/downloads")
def downloads():
    return render_template("downloads.html")

@app.route("/docs/index")
def docs_index():
    return render_template("docs/index.html")

@app.route("/docs/nodes")
def docs_nodes():
    return render_template("docs/nodes.html")

@app.route("/api/create_token/", methods=['GET'])
def create_token():
    with state_lock:
        room_id = 0
        while room_id == 0 or room_id in rooms:
            room_id = random.randint(1000, 9999)

        rooms[room_id] = {
            "nodes": [],
            "edges": [],
            "version": 0,
            "node_index": {},
            "edge_index": {},
            "created_at": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat()
        }
    return str(room_id)

@app.route("/api/get_data/", methods=['GET', 'POST'])
def get_data():
    if request.method == 'POST' and request.is_json:
        room_key = request.get_json().get("key")
    else:
        room_key = request.args.get("key")
    
    try:
        room_key = int(room_key)
    except (ValueError, TypeError):
        return "Invalid key format", 400
    
    with state_lock:
        if room_key not in rooms:
            return "Key does not exist", 400

        response = {
            "version": rooms[room_key]["version"],
            "nodes": rooms[room_key]["nodes"],
            "edges": rooms[room_key]["edges"]
        }
        return jsonify(response)

@app.route("/api/session_info/")
def session_info():
    with state_lock:
        response = {
            "active_sessions": len(active_sessions),
            "rooms": {
                room: len(clients) for room, clients in room_clients.items()
            }
        }
        return jsonify(response)

if __name__ == '__main__':
    app.run(host=sys.argv[1] if len(sys.argv) > 1 else '0.0.0.0', port=int(sys.argv[2] if len(sys.argv) > 2 else 5000), debug=True, threaded=True)
