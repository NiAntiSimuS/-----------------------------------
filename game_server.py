import asyncio
import argparse
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.templating import Jinja2Templates
import uvicorn
import httpx

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ---------- параметры командной строки ----------
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--token-x", type=str, required=True)
parser.add_argument("--token-o", type=str, required=True)
parser.add_argument("--host-url", type=str, required=True)
args = parser.parse_args()

PORT = args.port
TOKEN_X = args.token_x
TOKEN_O = args.token_o
HOST_URL = args.host_url

# ---------- состояние игры ----------
board = [""] * 9
turn = "X"          # X ходит первым
winner = None
tie = False
connections = {}    # role -> websocket

def check_winner():
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

async def broadcast_state():
    """Отправляет текущее состояние игры обоим игрокам."""
    for role, ws in connections.items():
        await ws.send_json({
            "board": board,
            "turn": turn,
            "winner": winner,
            "tie": tie,
            "your_role": role,
            "game_active": (winner is None and not tie)
        })

async def finish_game():
    """Отправляет результат на хост-сервер и завершает игровой процесс."""
    global winner, tie
    if winner is None and not tie:
        # Завершили из-за отключения игрока
        winner = "disconnect"
    # Отправляем результат
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"{HOST_URL}/result", json={
                "winner": winner,
                "players": [TOKEN_X, TOKEN_O],
                "port": PORT
            })
        except:
            pass
    # Завершаем процесс через 1 секунду
    asyncio.create_task(shutdown_after_delay())

async def shutdown_after_delay(delay=1.0):
    await asyncio.sleep(delay)
    raise SystemExit

@app.websocket("/ws/{role}")
async def game_ws(websocket: WebSocket, role: str):
    # Роль может быть "X" или "O"
    if role not in ("X", "O"):
        await websocket.close(code=1008, reason="Invalid role")
        return
    await websocket.accept()
    # Получаем токен от клиента
    try:
        data = await websocket.receive_json()
        token = data.get("token")
    except:
        await websocket.close(code=1008)
        return
    # Проверяем токен
    if (role == "X" and token != TOKEN_X) or (role == "O" and token != TOKEN_O):
        await websocket.close(code=1008, reason="Invalid token")
        return
    # Сохраняем соединение
    connections[role] = websocket
    # Уведомляем игрока о том, что он подключился
    await websocket.send_json({"type": "connected", "role": role})
    # Если уже подключились оба – начинаем игру
    if len(connections) == 2:
        await broadcast_state()
    try:
        while True:
            # Ждём ход от клиента
            msg = await websocket.receive_json()
            if msg.get("type") == "move":
                idx = msg.get("index")
                if winner or tie:
                    await websocket.send_json({"error": "Game finished"})
                    continue
                if turn != role:
                    await websocket.send_json({"error": "Not your turn"})
                    continue
                if board[idx] != "":
                    await websocket.send_json({"error": "Cell taken"})
                    continue
                # Делаем ход
                board[idx] = role
                res = check_winner()
                if res:
                    if res == "Tie":
                        tie = True
                    else:
                        winner = res
                    await broadcast_state()
                    await finish_game()   # игра окончена, шлём результат и выходим
                    break
                else:
                    turn = "O" if turn == "X" else "X"
                    await broadcast_state()
    except WebSocketDisconnect:
        # Игрок отключился – игра прерывается
        if winner is None and not tie:
            # Если игра ещё активна, объявляем поражение отключившегося
            if role == "X":
                winner = "O"
            else:
                winner = "X"
            await broadcast_state()
            await finish_game()
    finally:
        if role in connections:
            del connections[role]
        # Если оба отвалились – просто выходим
        if len(connections) == 0:
            await finish_game()

@app.get("/game")
async def game_page(request: Request):
    return templates.TemplateResponse("game.html", {"request": request})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)