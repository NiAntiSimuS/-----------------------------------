from flask import Flask, render_template, request, jsonify, redirect, url_for
import uuid

app = Flask(__name__)

games = {}

waiting_queue = []  

def generate_player_token():
    return str(uuid.uuid4())

def check_winner(board):
    win_positions = [
        [0,1,2], [3,4,5], [6,7,8],
        [0,3,6], [1,4,7], [2,5,8],
        [0,4,8], [2,4,6]
    ]
    for pos in win_positions:
        if board[pos[0]] == board[pos[1]] == board[pos[2]] != "":
            return board[pos[0]]
    if "" not in board:
        return "Tie"
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/game')
def game_page():
    room = request.args.get('room')
    role = request.args.get('role')
    token = request.args.get('token')
    if not room or not role or not token:
        return redirect(url_for('index'))
    #существует ли игра и соответствует ли токен
    if room not in games:
        return redirect(url_for('index'))
    game = games[room]
    if game['players'].get(role) != token:
        return redirect(url_for('index'))
    return render_template('game.html', room=room, role=role, token=token)

@app.route('/find_game', methods=['POST'])
def find_game():
    data = request.get_json()
    token = generate_player_token()
    player = (request.remote_addr, token)
    
    waiting_queue.append(player)
    
    #проверка
    if len(waiting_queue) >= 2:
        p1 = waiting_queue.pop(0)
        p2 = waiting_queue.pop(0)
        room_id = str(uuid.uuid4())
        #создание игры
        games[room_id] = {
            'board': [""] * 9,
            'turn': 'X',
            'winner': None,
            'tie': False,
            'players': {'X': p1[1], 'O': p2[1]}
        }
        return jsonify({
            'status': 'ready',
            'room': room_id,
            'role': 'X' if p1 == player else 'O',
            'token': p1[1] if p1 == player else p2[1]
        })
    else:
        #ожидани
        return jsonify({'status': 'waiting', 'token': token})

@app.route('/check_queue', methods=['POST'])
def check_queue():
    """Клиент периодически опрашивает этот эндпоинт, ожидая, пока его токен не попадёт в игру."""
    data = request.get_json()
    token = data.get('token')
    #поиск по токену игрока
    for room_id, game in games.items():
        if game['players']['X'] == token or game['players']['O'] == token:
            role = 'X' if game['players']['X'] == token else 'O'
            return jsonify({'status': 'ready', 'room': room_id, 'role': role, 'token': token})
    for (ip, t) in waiting_queue:
        if t == token:
            return jsonify({'status': 'waiting'})
    return jsonify({'status': 'error', 'message': 'Сессия не найдена'})

@app.route('/game_state/<room>')
def game_state(room):
    if room not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[room]
    return jsonify({
        'board': game['board'],
        'turn': game['turn'],
        'winner': game['winner'],
        'tie': game['tie']
    })

@app.route('/make_move', methods=['POST'])
def make_move():
    data = request.get_json()
    room = data.get('room')
    index = data.get('index')
    role = data.get('role')
    token = data.get('token')
    
    if room not in games:
        return jsonify({'error': 'Game not found'}), 404
    
    game = games[room]
    # проверка
    if game['players'].get(role) != token:
        return jsonify({'error': 'Invalid token'}), 403
    
    if game['winner'] or game['tie']:
        return jsonify({'error': 'Game already finished'}), 400
    
    if game['turn'] != role:
        return jsonify({'error': 'Not your turn'}), 400
    
    if game['board'][index] != "":
        return jsonify({'error': 'Cell already taken'}), 400
    
    #ходы
    game['board'][index] = role
    winner = check_winner(game['board'])
    if winner:
        if winner == "Tie":
            game['tie'] = True
        else:
            game['winner'] = winner
    else:
        game['turn'] = 'O' if game['turn'] == 'X' else 'X'
    
    return jsonify({'success': True})

@app.route('/leave_game', methods=['POST'])
def leave_game():
    data = request.get_json()
    room = data.get('room')
    token = data.get('token')
    if room in games:
        del games[room]
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)