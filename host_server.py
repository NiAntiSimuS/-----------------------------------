import asyncio
import subprocess
import sys
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.templating import Jinja2Templates
import uvicorn

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ---------- конфигурация ----------
HOST_IP = "0.0.0.0"          # адрес, на котором висит хост (внутри машины)
HOST_PORT = 8000
PORT_POOL = list(range(8001, 8011))   # доступные порты для игр
busy_ports = set()                    # занятые порты
processes = {}                        # порт -> Popen объект
waiting_players = []                  # очередь ожидающих WebSocket-соединений

# ---------- вспомогательные функции ----------
def get_free_port():
    for p in PORT_POOL:
        if p not in busy_ports:
            busy_ports.add(p)
            return p
    return None

def release_port(port):
    busy_ports.discard(port)
    if port in processes:
        proc = processes.pop(port)
        try:
            proc.terminate()
        except:
            pass

async def start_game_server(port, token_x, token_o):
    """Асинхронно запускает game_server.py и ждёт, пока он будет готов."""
    cmd = [
        sys.executable, "game_server.py",
        "--port", str(port),
        "--token-x", token_x,
        "--token-o", token_o,
        "--host-url", f"http://{HOST_IP}:{HOST_PORT}"
    ]
    # Запускаем процесс (без shell, список аргументов)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    processes[port] = proc
    # Даём серверу время подняться (можно улучшить healthcheck'ом)
    await asyncio.sleep(0.5)
    return proc

# ---------- WebSocket для очереди ----------
@app.websocket("/ws")
async def matchmaking(websocket: WebSocket):
    await websocket.accept()
    # Добавляем игрока в очередь
    waiting_players.append(websocket)
    try:
        # Пока игрок ждёт, он может отправить ping или мы просто ждём сбора пары
        while True:
            # Проверяем, не набралось ли два игрока
            if len(waiting_players) >= 2:
                p1 = waiting_players.pop(0)
                p2 = waiting_players.pop(0)
                # Генерируем токены
                token_x = str(uuid.uuid4())
                token_o = str(uuid.uuid4())
                port = get_free_port()
                if port is None:
                    # Нет свободных портов – возвращаем игроков обратно в очередь
                    waiting_players.extend([p1, p2])
                    await asyncio.sleep(1)
                    continue
                # Запускаем игровой сервер
                await start_game_server(port, token_x, token_o)
                # Отправляем каждому игроку его роль и токен
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
                # Закрываем соединения с хостом (игроки сами перейдут на игровой сервер)
                await p1.close()
                await p2.close()
            # Ждём, пока очередь не достигнет 2
            await asyncio.sleep(0.5)
            # Если текущий websocket отвалился, он будет удалён при исключении
    except WebSocketDisconnect:
        # Удаляем игрока из очереди, если он там был
        if websocket in waiting_players:
            waiting_players.remove(websocket)
    except Exception as e:
        print(f"Ошибка в очереди: {e}")

# ---------- Приём результатов от игровых серверов ----------
@app.post("/result")
async def game_result(winner: str = None, players: list = None, port: int = None):
    print(f"Игра на порту {port} завершена. Победитель: {winner}")
    # Освобождаем порт и завершаем процесс (сервер сам закроется, но подстрахуемся)
    release_port(port)
    return {"ok": True}

# ---------- Отдача HTML ----------
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    uvicorn.run(app, host=HOST_IP, port=HOST_PORT)