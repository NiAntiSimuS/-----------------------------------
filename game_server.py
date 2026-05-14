import asyncio
import argparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.templating import Jinja2Templates

import uvicorn
import httpx

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ---------------- ARGUMENTS ----------------

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

# ---------------- GAME STATE ----------------

board = [""] * 9

turn = "X"
winner = None
tie = False

connections = {}

# ---------------- GAME LOGIC ----------------

def check_winner():

    win_positions = [
        [0,1,2],
        [3,4,5],
        [6,7,8],

        [0,3,6],
        [1,4,7],
        [2,5,8],

        [0,4,8],
        [2,4,6]
    ]

    for p in win_positions:

        if (
            board[p[0]] ==
            board[p[1]] ==
            board[p[2]] != ""
        ):
            return board[p[0]]

    if "" not in board:
        return "Tie"

    return None


async def broadcast_state():

    for role, ws in list(connections.items()):

        try:
            await ws.send_json({
                "board": board,
                "turn": turn,
                "winner": winner,
                "tie": tie,
                "your_role": role
            })

        except:
            pass


async def finish_game():

    async with httpx.AsyncClient() as client:

        try:
            await client.post(
                f"{HOST_URL}/result",
                json={
                    "winner": winner,
                    "port": PORT
                }
            )

        except:
            pass

    await asyncio.sleep(1)

    raise SystemExit

# ---------------- WEBSOCKET ----------------

@app.websocket("/ws/{role}")
async def game_ws(websocket: WebSocket, role: str):

    global turn
    global winner
    global tie

    if role not in ("X", "O"):
        await websocket.close()
        return

    await websocket.accept()

    try:

        data = await websocket.receive_json()

        token = data.get("token")

        if role == "X" and token != TOKEN_X:
            await websocket.close()
            return

        if role == "O" and token != TOKEN_O:
            await websocket.close()
            return

        connections[role] = websocket

        await websocket.send_json({
            "type": "connected",
            "role": role
        })

        if len(connections) == 2:
            await broadcast_state()

        while True:

            msg = await websocket.receive_json()

            if msg.get("type") != "move":
                continue

            if winner or tie:
                continue

            if turn != role:
                continue

            idx = msg.get("index")

            if idx is None:
                continue

            if idx < 0 or idx > 8:
                continue

            if board[idx] != "":
                continue

            board[idx] = role

            result = check_winner()

            if result:

                if result == "Tie":
                    tie = True
                else:
                    winner = result

                await broadcast_state()

                await finish_game()

            else:

                turn = "O" if turn == "X" else "X"

                await broadcast_state()

    except WebSocketDisconnect:

        if role in connections:
            del connections[role]

        if winner is None:

            winner = "O" if role == "X" else "X"

            await broadcast_state()

            await finish_game()

# ---------------- PAGE ----------------

@app.get("/game")
async def game_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="game.html",
        context={"request": request}
    )

# ---------------- START ----------------

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT
    )