# Mein Chat (slackers)

Lightweight Flask + Socket.IO chat demo used for development.

Requirements
- Python 3.8+
- Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run

```bash
python app.py
# then open http://localhost:5000
```

Notes
- The app stores channels and messages in `channels.json` next to `app.py`.
- For development it's fine to use the default secret; set `FLASK_SECRET` in the environment for improved safety.
- `eventlet` is recommended for Socket.IO support; it's in `requirements.txt`.
