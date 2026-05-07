from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS

# Initialisierung
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dein-geheimer-schluessel'
CORS(app, resources={r"/*": {"origins": "*"}})

# SocketIO mit CORS-Unterstützung
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# Dictionary für alle verbundenen Clients (optional)
connected_clients = {}

@socketio.on('connect')
def handle_connect():
    """Wird aufgerufen, wenn ein Client eine Verbindung herstellt."""
    print(f'Client {request.sid} hat sich verbunden')
    connected_clients[request.sid] = {'room': None}
    emit('connection_response', {'data': f'Verbunden mit ID: {request.sid}'})

@socketio.on('disconnect')
def handle_disconnect():
    """Wird aufgerufen, wenn ein Client die Verbindung trennt."""
    print(f'Client {request.sid} hat getrennt')
    # Verlasse den Raum, falls vorhanden
    if request.sid in connected_clients and connected_clients[request.sid]['room']:
        leave_room(connected_clients[request.sid]['room'])
    if request.sid in connected_clients:
        del connected_clients[request.sid]

@socketio.on('join_room')
def handle_join_room(data):
    """Client tritt einem Raum bei."""
    room = data.get('room')
    if not room:
        return
    
    join_room(room)
    connected_clients[request.sid]['room'] = room
    print(f'Client {request.sid} ist Raum {room} beigetreten')
    
    # Allen anderen im Raum mitteilen
    emit('user_joined', {'message': f'User {request.sid} ist beigetreten'}, room=room)
    
    # Dem verbundenen Client eine Bestätigung senden
    emit('joined_room', {'room': room, 'sid': request.sid})

@socketio.on('diagram_update')
def handle_diagram_update(data):
    """
    Empfängt eine Diagramm-Änderung vom Client und leitet sie an alle anderen im Raum weiter.
    """
    room = data.get('room')
    if not room:
        return
    
    # Entferne 'room' aus den Daten, bevor sie weitergeleitet werden
    update_data = {k: v for k, v in data.items() if k != 'room'}
    
    # Die Nachricht an ALLE im Raum senden (außer dem Sender selbst, das ist optional)
    # Standardmäßig sendet emit an alle, inklusive Sender.
    # 'include_self=False' vermeidet Echo.
    emit('diagram_update', update_data, room=room, include_self=False)

@socketio.on('leave_room')
def handle_leave_room(data):
    """Client verlässt einen Raum."""
    room = data.get('room')
    if not room:
        return
    
    leave_room(room)
    if request.sid in connected_clients:
        connected_clients[request.sid]['room'] = None
    emit('user_left', {'message': f'User {request.sid} hat verlassen'}, room=room)

@socketio.on('get_room_state')
def handle_get_room_state(data):
    """
    Fordert den aktuellen Zustand eines Raums an.
    Der Server könnte den Zustand aus einer Datenbank oder einem Cache laden.
    """
    room = data.get('room')
    if not room:
        return
    
    # TODO: Hier den gespeicherten Diagrammzustand aus einer Datenbank laden
    # initial_state = load_diagram_state(room)
    # emit('room_state', initial_state, room=request.sid) # Nur an den Anforderer senden

if __name__ == '__main__':
    # Eventlet wird als Async-Server verwendet
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)