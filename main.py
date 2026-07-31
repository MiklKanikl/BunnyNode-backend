from flask import Flask, request, jsonify, render_template
import random
import uuid
import json
import asyncio
import websockets
import logging
from datetime import datetime
import threading
import os
from dotenv import load_dotenv

logging.basicConfig(
    format="%(asctime)s %(message)s",
    level=logging.DEBUG,
)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

if not app.config['SECRET_KEY']:
    raise ValueError("No SECRET_KEY set for Flask application")

rooms = {}
active_sessions = {}
room_clients = {}
websocket_clients = {}
loop = None

def create_session(room_key, user_info=None):
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
    if session_id in active_sessions:
        room = active_sessions[session_id]['room']
        if room in room_clients:
            room_clients[room].discard(session_id)
            if not room_clients[room]:
                del room_clients[room]
        del active_sessions[session_id]
        if session_id in websocket_clients:
            del websocket_clients[session_id]

def apply_delta(scene_key, changes):
    scene = rooms[scene_key]
    
    if changes["type"] == "nodes_added":
        for node in changes["nodes"]:
            scene["nodes"].append(node)
    
    if changes["type"] == "nodes_modified":
        for node_update in changes["nodes"]:
            node_id = node_update["id"]
            for n in scene["nodes"]:
                print(n["id"], "|n|", node_id)
                if n["id"] == node_id:
                    del n
            scene["nodes"].append(node_update)
    
    if changes["type"] == "nodes_and_edges_removed":
        for node_update in changes["nodes"]:
            node_id = node_update["id"]
            for n in scene["nodes"]:
                if n["id"] == node_id:
                    del n
        
        for edge_update in changes["edges"]:
            edge_id = edge_update["id"]
            for e in scene["edges"]:
                if e["id"] == edge_id:
                    del e
    
    if changes["type"] == "edges_added":
        for edge in changes["edges"]:
            scene["edges"].append(edge)
    
    if changes["type"] == "edges_modified":
        for edge_update in changes["edges"]:
            edge_id = edge_update.get("id")
            for e in scene["edges"]:
                print(e["id"], "|e|", edge_id)
                if e["id"] == edge_id:
                    del e
            scene["edges"].append(edge_update)

    if changes["type"] == "nodes_and_edges_added":
        for node in changes["nodes"]:
            scene["nodes"].append(node)
        
        for edge in changes["edges"]:
            scene["edges"].append(edge)
    
    rooms[scene_key] = scene
    print(rooms[scene_key])

async def broadcast_to_room(room_key, message, exclude_sid=None):
    if room_key not in room_clients:
        return
    for sid in room_clients[room_key]:
        if sid == exclude_sid:
            continue
        if sid in websocket_clients:
            try:
                await websocket_clients[sid].send(json.dumps(message))
            except:
                pass

async def websocket_handler(websocket):
    session_id = None
    room = None
    
    try:
        raw_msg = await websocket.recv()
        msg = json.loads(raw_msg)
        
        if msg.get('type') == 'join':
            room_key = int(msg.get('room'))
            user_info = msg.get('user_info', {})
            
            if room_key not in rooms:
                await websocket.send(json.dumps({
                    'type': 'error',
                    'message': 'Room not found'
                }))
                return
            
            session_id = create_session(room_key, user_info)
            websocket_clients[session_id] = websocket
            room = room_key
            
            await websocket.send(json.dumps({
                'type': 'joined',
                'session_id': session_id,
                'room': room_key,
                'version': rooms[room_key]['version'],
                'nodes': rooms[room_key]['nodes'],
                'edges': rooms[room_key]['edges']
            }))
            
            await broadcast_to_room(room_key, {
                'type': 'user_joined',
                'session_id': session_id,
                'user_info': active_sessions[session_id]['user_info'],
                'total_clients': len(room_clients.get(room_key, set()))
            })
            
            async for raw_msg in websocket:
                try:
                    msg = json.loads(raw_msg)
                    print(f"received message: {msg}")
                    msg_type = msg.get('type')
                    
                    if msg_type == 'scene_change':
                        changes = msg.get('changes')
                        version = msg.get('version')
                        
                        if room not in rooms:
                            continue
                        
                        if version != rooms[room]['version']:
                            await websocket.send(json.dumps({
                                'type': 'conflict',
                                'server_version': rooms[room]['version']
                            }))
                            continue
                        
                        apply_delta(room, changes)
                        rooms[room]['version'] += 1
                        rooms[room]['last_modified'] = datetime.now().isoformat()
                        
                        await broadcast_to_room(room, {
                            'type': 'scene_update',
                            'changes': changes,
                            'version': rooms[room]['version'],
                            'updated_by': session_id
                        }, exclude_sid=session_id)
                        
                        await websocket.send(json.dumps({
                            'type': 'update_success',
                            'new_version': rooms[room]['version']
                        }))
                    
                    elif msg_type == 'ping':
                        await websocket.send(json.dumps({'type': 'pong'}))
                    
                    elif msg_type == 'leave':
                        break
                        
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'Invalid JSON'
                    }))
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if session_id:
            if room:
                await broadcast_to_room(room, {
                    'type': 'user_left',
                    'session_id': session_id,
                    'user_info': active_sessions.get(session_id, {}).get('user_info')
                })
            remove_session(session_id)

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
    room_id = 0
    while room_id == 0 or room_id in rooms:
        room_id = random.randint(1000, 9999)
    
    rooms[room_id] = {
        "nodes": [],
        "edges": [],
        "version": 0,
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
    
    if room_key in rooms:
        return jsonify({
            "version": rooms[room_key]["version"],
            "nodes": rooms[room_key]["nodes"],
            "edges": rooms[room_key]["edges"]
        })
    else:
        return "Key does not exist", 400

@app.route("/api/session_info/")
def session_info():
    return jsonify({
        "active_sessions": len(active_sessions),
        "rooms": {
            room: len(clients) for room, clients in room_clients.items()
        }
    })

async def main():
    start_server = await websockets.serve(websocket_handler, "0.0.0.0", 8765)
    
    flask_thread = threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
    )
    flask_thread.daemon = True
    flask_thread.start()
    
    await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main())