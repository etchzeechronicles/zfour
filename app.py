import eventlet
eventlet.monkey_patch()

import sqlite3
import secrets
import json
import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_socketio import SocketIO, join_room, emit
from werkzeug.middleware.proxy_fix import ProxyFix


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-fallback-key")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

DB = "connect4.db"


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            invite_code TEXT UNIQUE NOT NULL,
            host_name TEXT NOT NULL,
            host_color TEXT NOT NULL,
            guest_name TEXT,
            guest_color TEXT NOT NULL,
            board TEXT NOT NULL,
            turn TEXT NOT NULL,
            status TEXT NOT NULL,
            winner TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def empty_board():
    return [[None for _ in range(7)] for _ in range(6)]


def get_game(game_id):
    conn = db()
    game = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    conn.close()
    return game


def save_game(game_id, board, turn, status, winner):
    conn = db()
    conn.execute("""
        UPDATE games
        SET board=?, turn=?, status=?, winner=?
        WHERE id=?
    """, (json.dumps(board), turn, status, winner, game_id))
    conn.commit()
    conn.close()


def public_game(game):
    return {
        "id": game["id"],
        "invite_code": game["invite_code"],
        "host_name": game["host_name"],
        "host_color": game["host_color"],
        "guest_name": game["guest_name"],
        "guest_color": game["guest_color"],
        "board": json.loads(game["board"]),
        "turn": game["turn"],
        "status": game["status"],
        "winner": game["winner"]
    }


def winner(board, row, col, color):
    directions = [(1, 0), (0, 1), (1, 1), (1, -1)]

    for dr, dc in directions:
        count = 1

        for direction in (1, -1):
            r = row + dr * direction
            c = col + dc * direction

            while 0 <= r < 6 and 0 <= c < 7 and board[r][c] == color:
                count += 1
                r += dr * direction
                c += dc * direction

        if count >= 4:
            return True

    return False


def board_full(board):
    return all(cell is not None for row in board for cell in row)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/game/<game_id>")
def game_page(game_id):
    game = get_game(game_id)
    if not game:
        return "Game not found", 404
    return render_template("game.html", game_id=game_id)


@app.route("/invite/<game_id>")
def invite_page(game_id):
    game = get_game(game_id)
    if not game:
        return "Invitation not found", 404
    return render_template("invite.html", game_id=game_id)


@app.post("/api/create")
def create_game():
    data = request.get_json() or {}
    name = str(data.get("name", "")).strip()
    color = data.get("color")

    if not name:
        return jsonify(error="Please enter your name."), 400

    if color not in ("red", "yellow"):
        return jsonify(error="Choose red or yellow."), 400

    game_id = secrets.token_urlsafe(12)
    invite_code = secrets.token_hex(4).upper()
    guest_color = "yellow" if color == "red" else "red"

    conn = db()
    conn.execute("""
        INSERT INTO games
        (id, invite_code, host_name, host_color, guest_color, board, turn, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        game_id,
        invite_code,
        name[:24],
        color,
        guest_color,
        json.dumps(empty_board()),
        "host",
        "waiting"
    ))
    conn.commit()
    conn.close()

    return jsonify(
        game_id=game_id,
        invite_code=invite_code,
        invite_url=url_for("invite_page", game_id=game_id, _external=True)
    )


@app.get("/api/invite/<game_id>")
def invite_info(game_id):
    game = get_game(game_id)

    if not game:
        return jsonify(error="Invitation not found."), 404

    return jsonify({
        "host_name": game["host_name"],
        "host_color": game["host_color"],
        "guest_color": game["guest_color"],
        "status": game["status"],
        "invite_code": game["invite_code"]
    })


@app.post("/api/join")
def join_game():
    data = request.get_json() or {}

    game_id = data.get("game_id")
    code = str(data.get("code", "")).strip().upper()
    name = str(data.get("name", "")).strip()

    game = get_game(game_id)

    if not game:
        return jsonify(error="Game not found."), 404

    if code != game["invite_code"]:
        return jsonify(error="Invalid invitation code."), 403

    if not name:
        return jsonify(error="Please enter your name."), 400

    if game["guest_name"]:
        return jsonify(error="This game already has two players."), 409

    conn = db()
    conn.execute("""
        UPDATE games
        SET guest_name=?, status='playing'
        WHERE id=?
    """, (name[:24], game_id))
    conn.commit()
    conn.close()

    socketio.emit("player_joined", room=game_id)

    return jsonify(success=True)


@app.get("/api/invite-by-code/<code>")
def invite_by_code(code):
    conn = db()
    game = conn.execute(
        "SELECT id FROM games WHERE invite_code=?",
        (code.strip().upper(),)
    ).fetchone()
    conn.close()

    if not game:
        return jsonify(error="Invitation not found."), 404

    return jsonify(game_id=game["id"])


@app.get("/api/game/<game_id>")
def game_state(game_id):
    game = get_game(game_id)

    if not game:
        return jsonify(error="Game not found."), 404

    return jsonify(public_game(game))


@app.post("/api/move")
def make_move():
    data = request.get_json() or {}

    game_id = data.get("game_id")
    column = data.get("column")
    role = data.get("role")

    game = get_game(game_id)

    if not game:
        return jsonify(error="Game not found."), 404

    if game["status"] != "playing":
        return jsonify(error="This game is not active."), 409

    if role not in ("host", "guest"):
        return jsonify(error="Invalid player."), 403

    if game["turn"] != role:
        return jsonify(error="It is not your turn."), 409

    try:
        column = int(column)
    except (ValueError, TypeError):
        return jsonify(error="Invalid column."), 400

    if not 0 <= column <= 6:
        return jsonify(error="Invalid column."), 400

    board = json.loads(game["board"])

    row = None
    for r in range(5, -1, -1):
        if board[r][column] is None:
            row = r
            break

    if row is None:
        return jsonify(error="That column is full."), 409

    color = game["host_color"] if role == "host" else game["guest_color"]
    board[row][column] = color

    did_win = winner(board, row, column, color)
    is_draw = board_full(board)

    if did_win:
        status = "finished"
        game_winner = role
        next_turn = role
    elif is_draw:
        status = "finished"
        game_winner = "draw"
        next_turn = role
    else:
        status = "playing"
        game_winner = None
        next_turn = "guest" if role == "host" else "host"

    save_game(game_id, board, next_turn, status, game_winner)

    # Notify the opponent via socket…
    socketio.emit("game_updated", room=game_id)

    # …and return the authoritative state to the player who just moved,
    # so their own board updates instantly without waiting for a broadcast.
    return jsonify(success=True, game=public_game(get_game(game_id)))


@socketio.on("join_game")
def socket_join(data):
    game_id = data.get("game_id")
    if game_id:
        join_room(game_id)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"ZFour running at http://127.0.0.1:{port}")
    socketio.run(app, host="0.0.0.0", port=port)