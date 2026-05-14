import asyncio
import sys
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.templating import Jinja2Templates
import uvicorn

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ---------------- CONFIG ----------------

HOST_IP = "0.0.0.0"
HOST_PORT = 8000

PORT_POOL = list(range(8001, 8011))

busy_ports = set()
processes = {}
waiting_players = []

# ---------------- HELPERS ----------------

def get_free_port():
    for port in PORT_POOL:
        if port not in busy_ports:
            busy_ports.add(port)
            return port
    return None


def release_port(port):
    busy_ports.discard(port)

    proc = processes.pop(port, None)

    if proc:
        try:
            proc.terminate()
        except:
            pass


async def start_game_server(port, token_x, token_o):
    cmd = [
        sys.executable,
        "game_server.py",
        "--port", str(port),
        "--token-x", token_x,
        "--token-o", token_o,
        "--host-url", f"http://127.0.0.1:{HOST_PORT}"
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd
    )

    processes[port] = proc

    await asyncio.sleep(1)

# ---------------- WEBSOCKET MATCHMAKING ----------------

@app.websocket("/ws")
async def matchmaking(websocket: WebSocket):
    await websocket.accept()

    waiting_players.append(websocket)

    try:
        while True:

            if len(waiting_players) >= 2:

                p1 = waiting_players.pop(0)
                p2 = waiting_players.pop(0)

                port = get_free_port()

                if port is None:
                    await asyncio.sleep(1)
                    continue

                token_x = str(uuid.uuid4())
                token_o = str(uuid.uuid4())

                await start_game_server(
                    port,
                    token_x,
                    token_o
                )

                await p1.send_json({
                    "type": "match_found",
                    "port": port,
                    "role": "X",
                    "token": token_x
                })

                await p2.send_json({
                    "type": "match_found",
                    "port": port,
                    "role": "O",
                    "token": token_o
                })

                await p1.close()
                await p2.close()

            await asyncio.sleep(0.5)

    except WebSocketDisconnect:

        if websocket in waiting_players:
            waiting_players.remove(websocket)

# ---------------- RESULT CALLBACK ----------------

@app.post("/result")
async def game_result(data: dict):

    port = data.get("port")
    winner = data.get("winner")

    print(f"Game finished on port {port}. Winner: {winner}")

    if port:
        release_port(port)

    return {"ok": True}

# ---------------- PAGES ----------------

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request}
    )

# ---------------- START ----------------

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST_IP,
        port=HOST_PORT
    )