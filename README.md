# FOUR — Online Connect Four

A complete two-player online Connect Four game built with Python.

## Features

- Two players only
- Private invitation links
- Invitation codes
- Accept invitation before joining
- Custom player names
- Red/yellow color selection
- Realtime moves with Flask-SocketIO
- SQLite database
- Server-side move validation
- Automatic win detection
- Draw detection
- Responsive mobile/desktop UI
- No AI APIs
- No external game APIs

## Requirements

Python 3.10+ recommended.

## Install

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

Linux/macOS:

```bash
source venv/bin/activate
```

Then:

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Playing with a friend

1. Player 1 creates a game.
2. Player 1 copies the invitation link.
3. Send the link to Player 2.
4. Player 2 opens it.
5. Player 2 enters their name.
6. Player 2 accepts the invitation.
7. Both players are placed into the same realtime game.
8. The server controls whose turn it is.

## Internet deployment

For internet play between different networks, deploy the project to a Python-compatible host such as Render, Railway, Fly.io, or a VPS.

Do not use Flask's development server for production.

Change this in `app.py`:

```python
app.config["SECRET_KEY"] = "change-this-secret-key"
```

to a long random secret before deploying.

## Important

The Socket.IO client is loaded from a CDN in `game.html`. If you want the project to be completely offline/self-contained, download the Socket.IO browser client into `static/js/` and change the script tag to point to that local file.
