import json
import os
from flask import Flask, request, redirect, url_for, render_template, session, abort
from flask_socketio import SocketIO
from collections import defaultdict
import datetime
import re
import uuid
from markupsafe import Markup, escape
from werkzeug.utils import secure_filename
import random
from flask import jsonify

app = Flask(__name__)
# prefer an environment-provided secret in production
app.secret_key = os.getenv('FLASK_SECRET', 'dev_secret')
app.config['TEMPLATES_AUTO_RELOAD'] = True
# allow cross-origin for local/dev; fine-tune in production
socketio = SocketIO(app, cors_allowed_origins="*")

# place channels.json next to this file so paths are predictable
BASE_DIR = os.path.dirname(__file__)
CHANNELS_FILE = os.path.join(BASE_DIR, 'channels.json')
AVATARS_FILE = os.path.join(BASE_DIR, 'avatars.json')
active_users = set()
SID_TO_USER = {}
USER_SOCKET_COUNT = defaultdict(int)

def load_channels():
    try:
        with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        # if file is corrupt, avoid crashing — return empty structure
        return {}

def load_avatars():
    try:
        with open(AVATARS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

def save_avatars(avatars):
    # ensure directory exists (AVATARS_FILE is typically in BASE_DIR)
    d = os.path.dirname(AVATARS_FILE) or '.'
    os.makedirs(d, exist_ok=True)
    tmp = AVATARS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(avatars, f, indent=2)
    try:
        os.replace(tmp, AVATARS_FILE)
    except OSError:
        with open(AVATARS_FILE, 'w', encoding='utf-8') as f:
            json.dump(avatars, f, indent=2)


def ensure_avatars_file_exists():
    # create an empty avatars file if missing to avoid race conditions
    try:
        if not os.path.exists(AVATARS_FILE):
            d = os.path.dirname(AVATARS_FILE) or '.'
            os.makedirs(d, exist_ok=True)
            with open(AVATARS_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
    except OSError:
        # non-fatal; callers will handle missing avatars gracefully
        pass


def _pick_color():
    # palette of soft colors
    palette = ['#5865f2', '#f04747', '#f59e0b', '#10b981', '#06b6d4', '#8b5cf6', '#ec4899', '#f97316']
    return random.choice(palette)


def _fg_for_bg(bg_hex):
    # compute luminance to choose black or white fg
    h = bg_hex.lstrip('#')
    if len(h) == 3:
        h = ''.join([c*2 for c in h])
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # luminance
    luminance = (0.299*r + 0.587*g + 0.114*b)/255
    return '#000000' if luminance > 0.6 else '#ffffff'


def generate_avatar_for(username):
    avatars = load_avatars()
    if username in avatars:
        return avatars[username]
    initials = ''.join([p[0] for p in username.split() if p])[:2].upper() or username[0:2].upper()
    bg = _pick_color()
    fg = _fg_for_bg(bg)
    # generate a deterministic pixel-art SVG avatar and save it to static/avatars
    try:
        hash_name = __import__('hashlib').sha256(username.encode('utf-8')).hexdigest()[:16]
        fname = f"{hash_name}.svg"
        save_dir = os.path.join(BASE_DIR, 'static', 'avatars')
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, fname)
        if not os.path.exists(path):
            # build an 8x8 symmetric pixel pattern driven by the hash
            bits = __import__('hashlib').sha256(username.encode('utf-8')).digest()
            grid_size = 8
            scale = 8
            w = grid_size * scale
            h = grid_size * scale
            # pick two colors: foreground (fg) and a secondary color derived from hash
            sec = '#' + __import__('hashlib').md5(username.encode('utf-8')).hexdigest()[:6]
            fore = fg
            back = bg
            rects = []
            for y in range(grid_size):
                for x in range((grid_size + 1)//2):
                    idx = (x + y* ((grid_size+1)//2)) % len(bits)
                    on = bits[idx] & 1
                    if on:
                        rx = x*scale
                        ry = y*scale
                        rects.append((rx, ry, scale, scale, fore))
                        # mirror
                        mx = (grid_size - 1 - x) * scale
                        if mx != rx:
                            rects.append((mx, ry, scale, scale, fore))
            svg_parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">', f'<rect width="100%" height="100%" fill="{back}"/>']
            for (rx, ry, rw, rh, col) in rects:
                svg_parts.append(f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" fill="{col}"/>')
            # small eyes/mouth for character feel (deterministic)
            eye_on = bits[0] & 3
            if eye_on & 1:
                svg_parts.append(f'<rect x="{scale*2}" y="{scale*2}" width="{scale}" height="{scale}" fill="{sec}"/>')
            if eye_on & 2:
                svg_parts.append(f'<rect x="{scale*5}" y="{scale*2}" width="{scale}" height="{scale}" fill="{sec}"/>')
            svg_parts.append('</svg>')
            svg = '\n'.join(svg_parts)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(svg)
        # compute URL relative to static
        try:
            url = url_for('static', filename='avatars/' + fname)
        except Exception:
            url = '/static/avatars/' + fname
    except Exception:
        url = None
    avatars[username] = {'initials': initials, 'bg': bg, 'fg': fg, 'url': url}
    save_avatars(avatars)
    return avatars[username]


def attach_avatars_to_message(msg, avatars):
    """Return a shallow-copy of message with `avatar` on message and each reply."""
    mm = dict(msg)
    mm['avatar'] = avatars.get(mm.get('user'))
    if 'replies' in mm and isinstance(mm['replies'], list):
        new_replies = []
        for r in mm['replies']:
            rr = dict(r)
            rr['avatar'] = avatars.get(rr.get('user'))
            new_replies.append(rr)
        # sort replies by timestamp ascending so UI can assume chronological order
        try:
            new_replies.sort(key=lambda x: x.get('timestamp') or '')
        except Exception:
            pass
        mm['replies'] = new_replies
    return mm


def _make_embed_html(text):
    # find first URL
    # match absolute http(s) URLs or root-relative URLs like /static/uploads/...
    url_re = re.compile(r"(https?://\S+|/[^\s]+)")
    parts = []
    last = 0
    for m in url_re.finditer(text):
        start, end = m.start(1), m.end(1)
        url = m.group(1).rstrip('.,)')
        parts.append(escape(text[last:start]))
        lower = url.lower()
        if any(lower.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')):
            parts.append(Markup(f"<br><img src=\"{escape(url)}\" alt=\"image\" style=\"max-width:320px;\">"))
        elif 'youtube.com/watch' in lower or 'youtu.be/' in lower:
            vid = None
            if 'v=' in url:
                q = url.split('v=', 1)[1]
                vid = q.split('&')[0]
            else:
                parts_split = url.split('/')
                vid = parts_split[-1].split('?')[0]
            if vid:
                embed = f'https://www.youtube.com/embed/{escape(vid)}'
                parts.append(Markup(f"<br><iframe width=\"560\" height=\"315\" src=\"{embed}\" frameborder=\"0\" allow=\"accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture\" allowfullscreen></iframe>"))
            else:
                parts.append(Markup(f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(url)}</a>'))
        elif 'open.spotify.com' in lower or lower.startswith('spotify:'):
            # support spotify URIs (spotify:track:ID) and open.spotify.com links
            sp_type = None
            sp_id = None
            try:
                if lower.startswith('spotify:'):
                    parts_sp = url.split(':')
                    if len(parts_sp) >= 3:
                        sp_type = parts_sp[1]
                        sp_id = parts_sp[2]
                else:
                    m2 = re.search(r'open\.spotify\.com\/(track|album|playlist)\/([A-Za-z0-9]+)', url)
                    if m2:
                        sp_type = m2.group(1)
                        sp_id = m2.group(2)
            except Exception:
                sp_type = None
                sp_id = None
            if sp_type and sp_id:
                embed = f'https://open.spotify.com/embed/{escape(sp_type)}/{escape(sp_id)}'
                parts.append(Markup(f"<br><iframe src=\"{embed}\" width=\"300\" height=\"80\" frameborder=\"0\" allow=\"encrypted-media\" style=\"border:none;overflow:hidden;\"></iframe>"))
            else:
                parts.append(Markup(f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(url)}</a>'))
        else:
            parts.append(Markup(f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(url)}</a>'))
        last = end
    parts.append(escape(text[last:]))
    return Markup('').join(parts)


def render_message_filter(text):
    return _make_embed_html(text)

# register filter
app.jinja_env.filters['render_message'] = render_message_filter

# uploads
ALLOWED_UPLOAD_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}


@app.route('/upload_image', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': 'no file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'empty filename'}), 400
    username = session.get('username')
    if not username:
        return jsonify({'error': 'not authenticated'}), 403
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in ALLOWED_UPLOAD_EXT:
        return jsonify({'error': 'invalid file type'}), 400
    save_dir = os.path.join(BASE_DIR, 'static', 'uploads')
    os.makedirs(save_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(save_dir, unique_name)
    file.save(path)
    url = url_for('static', filename='uploads/' + unique_name)
    return jsonify({'url': url})

def save_channels(channels):
    # write atomically where possible
    tmp_path = CHANNELS_FILE + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(channels, f, indent=2)
    try:
        os.replace(tmp_path, CHANNELS_FILE)
    except OSError:
        # fallback to non-atomic write
        with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(channels, f, indent=2)


def backfill_reply_timestamps(channels):
    """Ensure every reply has a timestamp. Returns True if channels modified."""
    modified = False
    for msgs in channels.values():
        if not isinstance(msgs, list):
            continue
        for m in msgs:
            parent_ts = m.get('timestamp')
            replies = m.get('replies')
            if not replies or not isinstance(replies, list):
                continue
            for r in replies:
                if not isinstance(r, dict):
                    continue
                if not r.get('timestamp'):
                    # use parent timestamp if available, else current time
                    r['timestamp'] = parent_ts or datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    modified = True
    return modified

@app.route('/', methods=['GET'])
def index():
    channels = load_channels()
    first_channel = list(channels.keys())[0] if channels else ''
    username = session.get('username')
    return render_template('index.html', first_channel=first_channel, username=username)

@app.route('/channel/<channel>', methods=['GET', 'POST'])
def channel_view(channel):
    channels = load_channels()
    # backfill missing timestamps on replies for legacy data
    try:
        if backfill_reply_timestamps(channels):
            save_channels(channels)
    except (OSError, TypeError):
        pass
    if channel not in channels:
        return redirect(url_for('index'))
    username = session.get('username', 'anonymous')
    if request.method == 'POST':
        message = request.form.get('message')
        if message:
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            msg = {'user': username, 'message': message, 'timestamp': timestamp}
            channels[channel].append(msg)
            save_channels(channels)
            # index of the newly appended message
            msg_idx = len(channels[channel]) - 1
            # Emit a SocketIO event to notify clients with index and full message
            # attach avatar data if present
            avatars = load_avatars()
            msg_with_avatar = attach_avatars_to_message(msg, avatars)
            socketio.emit('new_message', {
                'channel': channel,
                'msg_idx': msg_idx,
                'message': msg_with_avatar,
            })
        # redirect back to the newly posted message anchor to avoid jumping to top
        return redirect(url_for('channel_view', channel=channel, _anchor=f'msg-{msg_idx}'))
    avatars = load_avatars()
    # ensure avatars exist for message authors and reply authors (generate if missing)
    try:
        for m in channels[channel]:
            u = m.get('user')
            if u and u not in avatars:
                try:
                    generate_avatar_for(u)
                except Exception:
                    pass
                avatars = load_avatars()
            replies = m.get('replies') or []
            if isinstance(replies, list):
                for r in replies:
                    ru = r.get('user')
                    if ru and ru not in avatars:
                        try:
                            generate_avatar_for(ru)
                        except Exception:
                            pass
                        avatars = load_avatars()
    except Exception:
        # non-fatal; proceed with whatever avatars we have
        pass

    # augment messages with avatar info if available
    msgs = []
    for m in channels[channel]:
        mm = attach_avatars_to_message(m, avatars)
        msgs.append(mm)
    return render_template('channel.html', channel=channel, messages=msgs, username=username, channels_list=list(channels.keys()), active_users=list(active_users), avatars=avatars)

@app.route('/channel/<channel>/react/<int:msg_idx>', methods=['POST'])
def add_reaction(channel, msg_idx):
    channels = load_channels()
    reaction = request.form.get('reaction')
    if channel in channels and reaction:
        try:
            msg = channels[channel][msg_idx]
        except (IndexError, ValueError):
            return abort(404)
        if 'reactions' not in msg:
            msg['reactions'] = []
        msg['reactions'].append(reaction)
        save_channels(channels)
        # notify clients to update this message
        avatars = load_avatars()
        msg_with_avatar = attach_avatars_to_message(msg, avatars)
        socketio.emit('update_message', {'channel': channel, 'msg_idx': msg_idx, 'message': msg_with_avatar})
    return redirect(url_for('channel_view', channel=channel, _anchor=f'msg-{msg_idx}'))

@app.route('/channel/<channel>/reply/<int:msg_idx>', methods=['POST'])
def add_reply(channel, msg_idx):
    channels = load_channels()
    reply_user = session.get('username', 'anonymous')
    reply_message = request.form.get('reply_message')
    if channel in channels and reply_message:
        try:
            msg = channels[channel][msg_idx]
        except (IndexError, ValueError):
            return abort(404)
        if 'replies' not in msg:
            msg['replies'] = []
        # add timestamp for each reply for richer UI
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg['replies'].append({'user': reply_user, 'message': reply_message, 'timestamp': ts})
        save_channels(channels)
        avatars = load_avatars()
        msg_with_avatar = attach_avatars_to_message(msg, avatars)
        socketio.emit('update_message', {'channel': channel, 'msg_idx': msg_idx, 'message': msg_with_avatar})
    return redirect(url_for('channel_view', channel=channel, _anchor=f'msg-{msg_idx}'))

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    if username:
        session['username'] = username
        # ensure avatar exists for this user
        # attempt to generate avatar; ignore file-write problems non-fatally
        try:
            generate_avatar_for(username)
        except OSError:
            pass
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    username = session.pop('username', None)
    if username:
        # remove user from active_users and clear socket tracking
        if username in active_users:
            active_users.remove(username)
        # remove any sids associated with this username
        sids_to_remove = [sid for sid, u in list(SID_TO_USER.items()) if u == username]
        for sid in sids_to_remove:
            SID_TO_USER.pop(sid, None)
        USER_SOCKET_COUNT.pop(username, None)
        socketio.emit('presence_update', {'active_users': list(active_users)})
    return redirect(url_for('index'))


@socketio.on('connect')
def handle_connect():
    # `session` is available here via Flask-SocketIO
    username = session.get('username')
    sid = request.sid
    if username:
        SID_TO_USER[sid] = username
        USER_SOCKET_COUNT[username] += 1
        if USER_SOCKET_COUNT[username] == 1:
            active_users.add(username)
            socketio.emit('presence_update', {'active_users': list(active_users)})


@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    username = SID_TO_USER.pop(sid, None)
    if username:
        USER_SOCKET_COUNT[username] -= 1
        if USER_SOCKET_COUNT[username] <= 0:
            USER_SOCKET_COUNT.pop(username, None)
            if username in active_users:
                active_users.remove(username)
                socketio.emit('presence_update', {'active_users': list(active_users)})

@app.route('/create_channel', methods=['POST'])
def create_channel():
    channels = load_channels()
    name = (request.form.get('name') or '').strip()
    if not name:
        return redirect(url_for('index'))
    # ensure channel names start with '#'
    if not name.startswith('#'):
        name = '#' + name
    # avoid duplicate when equivalent name exists
    if name not in channels:
        channels[name] = []
        save_channels(channels)
    return redirect(url_for('channel_view', channel=name))

if __name__ == '__main__':
    # make sure avatars file exists before the app starts
    ensure_avatars_file_exists()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
