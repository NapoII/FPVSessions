

from flask import Flask, render_template, send_from_directory, url_for, request, jsonify, session, redirect, flash, make_response
from urllib.parse import unquote
import os
import calendar
from datetime import date, datetime
from functools import wraps
import random
import json
import hashlib
import shutil
from threading import Lock
import subprocess
import sys
import time
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from .utils.session_utils import (
        get_cached_sessions,
        build_date_index,
        start_background_thumb_job,
        get_session_tags,
        save_session_tags,
    )
except Exception:
    # Fallback: Script-Start (python flask_app/app.py)
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from flask_app.utils.session_utils import (
        get_cached_sessions,
        build_date_index,
        start_background_thumb_job,
        get_session_tags,
        save_session_tags,
    )

app = Flask(__name__)

# Configure secret key for session management
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'fpv-session-secret-key-change-in-production')

# Configuration file path (JSON)
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'sessions_config.json')

def _load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception:
        return False

"""
Determine FPV_BASE with safe defaults:
- Prefer sessions_config.json FPV_BASE
- Else env FPV_BASE
- Else default to ./FPVSessions in the project
Never fall back to a Windows drive path on Linux.
"""
FPV_BASE = None
_cfg_boot = _load_config()
if isinstance(_cfg_boot, dict) and _cfg_boot.get('FPV_BASE'):
    FPV_BASE = _cfg_boot.get('FPV_BASE')
else:
    FPV_BASE = os.environ.get('FPV_BASE')
if not FPV_BASE:
    FPV_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'FPVSessions'))
#    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'H:/FPV/my_FPV/FPVSessions'))
#    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'FPVSessions'))

# old_login static route removed after migrating assets to /static/login

# Word list for generating share links
SHARE_WORDS = [
    'falcon', 'eagle', 'swift', 'drone', 'pilot', 'flight', 'soar', 'glide', 'zoom', 'dash',
    'blue', 'red', 'green', 'silver', 'gold', 'black', 'white', 'purple', 'orange', 'yellow',
    'fast', 'quick', 'smooth', 'bold', 'sharp', 'bright', 'cool', 'hot', 'wild', 'free',
    'sky', 'cloud', 'wind', 'storm', 'rain', 'sun', 'moon', 'star', 'fire', 'ice',
    'mountain', 'valley', 'river', 'forest', 'desert', 'ocean', 'beach', 'hill', 'field', 'lake',
    'power', 'speed', 'force', 'energy', 'boost', 'charge', 'spark', 'flash', 'beam', 'wave'
]

# Store for share links (in production, use database)
SHARE_LINKS = {}

# Simple file-backed user store (username -> {password_hash, login_count})
USERS_FILE = os.path.join(os.path.dirname(__file__), 'users.json')
_users_lock = Lock()

# Track currently-active logged-in users (in-memory)
_active_lock = Lock()
ACTIVE_USERS = set()
REVOKED_USERS = set()

# Drone images directory (admin-managed)
DRONE_DIR = os.path.join(os.path.dirname(__file__), 'static', 'login', 'drones')
ALLOWED_DRONE_EXT = {'.png', '.webp'}

def _ensure_drone_dir():
    try:
        os.makedirs(DRONE_DIR, exist_ok=True)
    except Exception:
        pass

def _load_users():
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_users(data):
    try:
        with _users_lock:
            with open(USERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        return True
    except Exception:
        return False

def _ensure_default_user():
    users = _load_users()
    if users:
        return
    # Add env-configured user as default
    expected_user = os.environ.get('FPVWEB_USER', 'admin')
    expected_pass = os.environ.get('FPVWEB_PASS', 'admin')
    users[expected_user] = {
        'password_hash': generate_password_hash(expected_pass),
        'login_count': 0
    }
    _save_users(users)


def generate_share_link():
    """Generate a unique share link with 3 random words"""
    words = random.sample(SHARE_WORDS, 3)
    link_id = '-'.join(words)
    return link_id

def save_share_link(link_id, video_path, session_name, session_sub):
    """Save a share link mapping"""
    SHARE_LINKS[link_id] = {
        'video_path': video_path,
        'session_name': session_name,
        'session_sub': session_sub,
        'created_at': date.today().isoformat()
    }
    return link_id

@app.route('/')
def index():
    # Validate base path; if missing, don't crash and surface an admin hint
    base_exists = bool(FPV_BASE) and os.path.isdir(FPV_BASE)
    sessions = get_cached_sessions(FPV_BASE) if base_exists else []
    # einfache Suche über q: match in Name, Sub, Tags
    q = (request.args.get('q') or '').strip().lower()
    if q:
        def matches(s):
            if q in s.get('name','').lower() or q in s.get('sub','').lower():
                return True
            for t in s.get('tags', []):
                if q in t.lower():
                    return True
            return False
        sessions = [s for s in sessions if matches(s)]
    date_map, months = build_date_index(sessions)
    # Aggregate stats for display
    def _safe_int(x, default=0):
        try:
            return int(x)
        except Exception:
            return default
    total_sessions = len(sessions)
    total_videos = sum(_safe_int(s.get('video_count', 0)) for s in sessions)
    total_minutes = sum(_safe_int((s.get('times') or {}).get('duration_min', 0)) for s in sessions)
    # Sum file sizes of all videos
    total_size_bytes = 0
    # Track oldest/newest video modification times across all videos
    min_mtime = None
    max_mtime = None
    for s in sessions:
        for rel in s.get('videos', []):
            try:
                abs_path = os.path.join(FPV_BASE, rel.replace('/', os.sep))
                total_size_bytes += os.path.getsize(abs_path)
                try:
                    if os.path.exists(abs_path):
                        m = os.path.getmtime(abs_path)
                        if min_mtime is None or m < min_mtime:
                            min_mtime = m
                        if max_mtime is None or m > max_mtime:
                            max_mtime = m
                except Exception:
                    pass
            except Exception:
                pass
    def human_size(n):
        units = ['B','KB','MB','GB','TB']
        size = float(n)
        i = 0
        while size >= 1024 and i < len(units)-1:
            size /= 1024.0
            i += 1
        return f"{size:.1f} {units[i]}"
    def human_duration(mins):
        try:
            mins = int(mins)
        except Exception:
            mins = 0
        hours = mins // 60
        rem = mins % 60
        return f"{hours}h {rem:02d}m" if hours else f"{rem}m"
    stats = {
        'sessions': total_sessions,
        'videos': total_videos,
        'total_minutes': total_minutes,
        'total_duration_human': human_duration(total_minutes),
        'total_size_bytes': total_size_bytes,
        'total_size_human': human_size(total_size_bytes),
    }
    # Count tags across sessions
    try:
        total_tags = 0
        unique_tags = set()
        for s in sessions:
            tags = s.get('tags') or []
            if isinstance(tags, list):
                total_tags += len(tags)
                for t in tags:
                    try:
                        if t:
                            unique_tags.add(str(t).strip().lower())
                    except Exception:
                        pass
        stats['tags_total'] = total_tags
        stats['tags_unique'] = len(unique_tags)
    except Exception:
        stats['tags_total'] = 0
        stats['tags_unique'] = 0
    # Format oldest/newest video timestamps for display
    def _fmt_ts(ts):
        try:
            if not ts:
                return ''
            return datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d %H:%M')
        except Exception:
            return ''
    stats['oldest_video'] = _fmt_ts(min_mtime)
    stats['newest_video'] = _fmt_ts(max_mtime)
    # Month navigation: default current month; allow prev/next by query
    today = date.today()
    try:
        year = int(request.args.get('year', today.year))
        month = int(request.args.get('month', today.month))
    except Exception:
        year, month = today.year, today.month
    # clamp month/year
    if month < 1:
        month = 12; year -= 1
    if month > 12:
        month = 1; year += 1
    cal = calendar.Calendar(firstweekday=0)  # Monday=0 in Python docs? Actually Monday=0; but we want Mo..So display in UI.
    month_days = [d for d in cal.itermonthdates(year, month)]
    # Build a matrix of weeks (each 7 days), mark if session exists for date
    weeks = []
    week = []
    today_iso = date.today().isoformat()
    for d in month_days:
        week.append({
            'date': d.isoformat(),
            'day': d.day,
            'in_month': (d.month == month),
            'has': bool(date_map.get(d.isoformat(), [])),
            'is_today': (d.isoformat() == today_iso)
        })
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        while len(week) < 7:
            week.append({'date':'', 'day':'', 'in_month':False, 'has': False})
        weeks.append(week)
    # Hintergrund-Job anstoßen (Thumbnails generieren), blockiert nicht
    if base_exists:
        start_background_thumb_job(FPV_BASE)
    # Pop just_logged_in flag so the sound plays only once
    try:
        just_logged_in = bool(session.pop('just_logged_in', False))
    except Exception:
        just_logged_in = False
    # detect if configured admin is still using the literal default password 'admin'
    admin_password_is_default = False
    try:
        expected_admin = os.environ.get('FPVWEB_USER', 'admin')
        users = _load_users()
        if expected_admin in users:
            ph = users[expected_admin].get('password_hash', '')
            if ph and check_password_hash(ph, 'admin'):
                admin_password_is_default = True
        else:
            # no file-based user; fall back to env configured password
            if os.environ.get('FPVWEB_PASS', 'admin') == 'admin':
                admin_password_is_default = True
    except Exception:
        admin_password_is_default = False
    # allow per-session suppression: if the admin chose 'don't show again' this session, don't prompt
    try:
        if session.get('suppress_admin_pw_prompt'):
            admin_password_is_default = False
    except Exception:
        pass
    return render_template(
        'modern_index_with_calendar.html',
        sessions=sessions,
        date_map=date_map,
        months=months,
        q=q,
        year=year,
        month=month,
    weeks=weeks,
    stats=stats,
    just_logged_in=just_logged_in,
    admin_password_is_default=admin_password_is_default,
    fpv_base_exists=base_exists,
    fpv_base_path=FPV_BASE
    )


@app.route('/api/admin/suppress-default-pw', methods=['POST'])
def api_admin_suppress_default_pw():
    # only admin may suppress for their session
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error': 'admin required'}), 403
    try:
        session['suppress_admin_pw_prompt'] = True
        return jsonify({'ok': True})
    except Exception:
        return jsonify({'error': 'failed'}), 500

@app.route('/session/<session_name>/<sub>')
def session_detail(session_name, sub):
    if not session.get('user'):
        return redirect(url_for('login', next=request.path))
    sessions = get_cached_sessions(FPV_BASE)
    for s in sessions:
        if s['name'] == session_name and s['sub'] == sub:
            # Compute session-specific stats
            def _human_size(n):
                units = ['B','KB','MB','GB','TB']
                size = float(n)
                i = 0
                while size >= 1024 and i < len(units)-1:
                    size /= 1024.0
                    i += 1
                return f"{size:.1f} {units[i]}"
            def _human_duration(mins):
                try:
                    mins = int(mins)
                except Exception:
                    mins = 0
                hours = mins // 60
                rem = mins % 60
                return f"{hours}h {rem:02d}m" if hours else f"{rem}m"
            total_size_bytes = 0
            for rel in s.get('videos', []):
                try:
                    abs_path = os.path.join(FPV_BASE, rel.replace('/', os.sep))
                    total_size_bytes += os.path.getsize(abs_path)
                except Exception:
                    pass
            s_stats = {
                'videos': s.get('video_count', 0),
                'images': s.get('image_count', 0),
                'duration_min': (s.get('times') or {}).get('duration_min', 0),
                'duration_human': _human_duration((s.get('times') or {}).get('duration_min', 0)),
                'size_bytes': total_size_bytes,
                'size_human': _human_size(total_size_bytes),
            }
            return render_template('session_detail.html', session=s, s_stats=s_stats)
    return 'Session nicht gefunden', 404

@app.route('/download/<path:filepath>')
def download(filepath):
    dirpath = FPV_BASE
    return send_from_directory(dirpath, filepath, as_attachment=True)

@app.route('/media/<path:filepath>')
def media(filepath):
    # Medien inline streamen (mit Range/Partial Content via conditional)
    dirpath = FPV_BASE
    # Robust resolution: unquote path, normalize and ensure it resolves under FPV_BASE
    try:
        req = unquote(filepath or '')
    except Exception:
        req = filepath

    # Try the straightforward resolved path firsts
    norm = os.path.abspath(os.path.normpath(os.path.join(dirpath, *([p for p in req.split('/') if p]))))
    def _send(rel_path):
        resp = send_from_directory(dirpath, rel_path, as_attachment=False, conditional=True)
        try:
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers.setdefault('Accept-Ranges', 'bytes')
        except Exception:
            pass
        return resp

    base_abs = os.path.abspath(dirpath)
    if os.path.exists(norm) and norm.startswith(base_abs):
        rel = os.path.relpath(norm, dirpath).replace('\\', '/')
        return _send(rel)

    # Fallback: try relative join (in case filepath already included session prefixes)
    try:
        alt = os.path.abspath(os.path.normpath(os.path.join(dirpath, req.replace('/', os.sep))))
        if os.path.exists(alt) and alt.startswith(base_abs):
            rel = os.path.relpath(alt, dirpath).replace('\\', '/')
            return _send(rel)
    except Exception:
        pass

    # Final fallback: search for file by basename under FPV_BASE (expensive but useful during dev)
    try:
        target_basename = os.path.basename(req)
        for root, dirs, files in os.walk(dirpath):
            if target_basename in files:
                found = os.path.join(root, target_basename)
                rel = os.path.relpath(found, dirpath).replace('\\', '/')
                return _send(rel)
    except Exception:
        pass

    return ('Not Found', 404)

@app.route('/api/session/<session>/<sub>/tags', methods=['GET', 'POST'])
def api_session_tags(session, sub):
    if request.method == 'GET':
        tags = get_session_tags(FPV_BASE, session, sub)
        return jsonify({'tags': tags})
    data = request.get_json(silent=True) or {}
    # Require permission to edit tags for non-admin users
    current = session.get('user')
    is_admin = (current == os.environ.get('FPVWEB_USER', 'admin'))
    if not is_admin:
        try:
            users = _load_users() or {}
            perms = users.get(current, {}).get('permissions', {}) or {}
            if not perms.get('edit_tags'):
                return jsonify({'error': 'permission denied'}), 403
        except Exception:
            return jsonify({'error': 'permission denied'}), 403
    tags = data.get('tags')
    if not isinstance(tags, list):
        return jsonify({'error': 'tags must be a list'}), 400
    tags = save_session_tags(FPV_BASE, session, sub, tags)
    return jsonify({'tags': tags})


def _resolve_session_path(session_folder: str, sub: str, filename: str):
    """Return absolute path under FPV_BASE for given session/sub and filename or None if invalid."""
    try:
        # basic sanitation: no .. segments
        if '..' in filename or filename.startswith(('/', '\\')):
            return None
        rel = os.path.join(session_folder, sub, filename)
        abs_path = os.path.abspath(os.path.normpath(os.path.join(FPV_BASE, rel)))
        base = os.path.abspath(FPV_BASE)
        if abs_path.startswith(base) and os.path.commonpath([abs_path, base]) == base:
            return abs_path
    except Exception:
        pass
    return None


@app.route('/api/session/<session_folder>/<sub>/log', methods=['GET'])
def api_get_session_log(session_folder, sub):
    # Require authentication
    if not session.get('user'):
        return jsonify({'error': 'authentication required'}), 401
    # Find the primary .txt log in session.logs if present
    sessions = get_cached_sessions(FPV_BASE)
    for s in sessions:
        if s['name'] == session_folder and s['sub'] == sub:
            # prefer first .txt in logs list
            logs = s.get('logs') or []
            if not logs:
                return jsonify({'error': 'no log found'}), 404
            # choose first log filename
            rel = logs[0]
            fname = os.path.basename(rel)
            abs_path = _resolve_session_path(session_folder, sub, fname)
            if not abs_path or not os.path.exists(abs_path):
                return jsonify({'error': 'not found'}), 404
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return jsonify({'filename': fname, 'content': content})
            except Exception as e:
                return jsonify({'error': 'could not read file', 'detail': str(e)}), 500
    return jsonify({'error':'session not found'}), 404


@app.route('/api/session/<session_folder>/<sub>/log', methods=['POST'])
def api_save_session_log(session_folder, sub):
    # Require authentication and permission
    current = session.get('user')
    if not current:
        return jsonify({'error': 'authentication required'}), 401
    is_admin = (current == os.environ.get('FPVWEB_USER', 'admin'))
    if not is_admin:
        try:
            users = _load_users() or {}
            perms = users.get(current, {}).get('permissions', {}) or {}
            if not perms.get('edit_logs'):
                return jsonify({'error': 'permission denied'}), 403
        except Exception:
            return jsonify({'error': 'permission denied'}), 403

    data = request.get_json(silent=True) or {}
    content = data.get('content')
    if content is None:
        return jsonify({'error':'content required'}), 400

    # locate primary log filename from session metadata
    sessions = get_cached_sessions(FPV_BASE)
    for s in sessions:
        if s['name'] == session_folder and s['sub'] == sub:
            logs = s.get('logs') or []
            if not logs:
                return jsonify({'error':'no log found to overwrite'}), 404
            rel = logs[0]
            fname = os.path.basename(rel)
            abs_path = _resolve_session_path(session_folder, sub, fname)
            if not abs_path:
                return jsonify({'error':'invalid path'}), 400
            try:
                # create a timestamped backup of existing file before overwriting
                try:
                    if os.path.exists(abs_path):
                        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                        bak = abs_path + f'.bak.{ts}'
                        shutil.copy2(abs_path, bak)
                except Exception:
                    # backup failure should not prevent saving, but log to stdout
                    print('⚠️ Backup failed for', abs_path)

                with open(abs_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                # Update cache in-memory if present
                # no additional cache action required here
                return jsonify({'ok': True, 'filename': fname})
            except Exception as e:
                return jsonify({'error': 'could not save file', 'detail': str(e)}), 500
    return jsonify({'error':'session not found'}), 404

@app.route('/api/status')
def api_status():
    # Report build/background status so UI can show progress
    try:
        from .utils import session_utils as su
    except Exception:
        import flask_app.utils.session_utils as su

    # If cache not initialized, kick off a build quickly
    if su._CACHE.get('sessions') is None and not su._CACHE.get('building', False):
        try:
            _ = su.get_cached_sessions(FPV_BASE)
        except Exception as e:
            print('api_status warm trigger failed:', e)

    building = bool(su._CACHE.get('building', False))
    last_built = su._CACHE.get('last_built', 0.0)
    sessions = su._CACHE.get('sessions') or []
    progress = int(su._CACHE.get('progress', 0) or 0)

    # When not building, treat as ready and force progress to 100 if we've ever built or have sessions
    if not building:
        if sessions:
            progress = 100
        # If we've built at least once (even zero sessions), consider UI ready
        if last_built and last_built > 0:
            progress = max(progress, 100)

    ready = (not building) or (len(sessions) > 0) or progress >= 100 or (last_built and last_built > 0)

    return jsonify({
        'building': building,
        'last_built': last_built,
        'session_count': len(sessions),
        'progress': progress,
        'ready': bool(ready),
    })

# Flask 3.x: before_first_request removed. Do a thread-safe warm-once on first request.
_warm_done = False
_warm_lock = Lock()

def _warm_cache_once():
    global _warm_done
    if _warm_done:
        return
    with _warm_lock:
        if _warm_done:
            return
        # Warm up sessions cache and start background job
        try:
            _ = get_cached_sessions(FPV_BASE)
        except Exception as e:
            print('Warm cache failed:', e)
        try:
            start_background_thumb_job(FPV_BASE)
        except Exception as e:
            print('Start thumb job failed:', e)
        _warm_done = True

@app.before_request
def _ensure_warm_cache():
    # Skip static to reduce overhead
    try:
        ep = request.endpoint or ''
        p = request.path or ''
        if ep == 'static' or ep == 'media' or ep == 'download' or ep.endswith('.shared_video_embed'):
            return
        if p.startswith('/static/') or p.startswith('/media/') or p.startswith('/favicon') or p.startswith('/robots.txt'):
            return
    except Exception:
        pass
    _warm_cache_once()


# Inject user info into all templates so we can show admin-only UI
@app.context_processor
def inject_user():
    try:
        current = session.get('user')
        is_admin = (current == os.environ.get('FPVWEB_USER', 'admin'))
    except Exception:
        current = None
        is_admin = False
    # determine permissions for current user from users file if present
    can_share = False
    can_edit_tags = False
    can_edit_logs = False
    can_create_sessions = False
    try:
        users = _load_users() or {}
        if is_admin:
            can_share = True
            can_edit_tags = True
            can_edit_logs = True
            can_create_sessions = True
        elif current and current in users:
            perms = users.get(current, {}).get('permissions', {}) or {}
            can_share = bool(perms.get('share'))
            can_edit_tags = bool(perms.get('edit_tags'))
            can_edit_logs = bool(perms.get('edit_logs'))
            can_create_sessions = bool(perms.get('create_sessions'))
    except Exception:
        can_share = False
        can_edit_tags = False
        can_edit_logs = False
    return {
        'current_user': current,
        'is_admin': is_admin,
        'can_share': can_share,
        'can_edit_tags': can_edit_tags,
    'can_edit_logs': can_edit_logs,
    'can_create_sessions': can_create_sessions
    }


# --- Admin settings (admin only) ---
@app.route('/admin/settings')
def admin_settings():
    # Only allow the configured FPVWEB_USER (default 'admin')
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return redirect(url_for('login', next=request.path))
    # simple settings page placeholder
    # include FPV_BASE value for editing
    return render_template('admin_settings.html', FPV_BASE=FPV_BASE, config={'FPVWEB_USER': os.environ.get('FPVWEB_USER','admin')})


# Admin API: set sessions folder (FPV_BASE) and rebuild cache
@app.route('/api/admin/sessions-folder', methods=['POST'])
def api_admin_sessions_folder():
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error': 'admin required'}), 403
    data = request.get_json(silent=True) or {}
    new_path = (data.get('sessions_folder') or '').strip()
    if not new_path:
        return jsonify({'error': 'sessions_folder required'}), 400
    # allow non-existing? Prefer to require existing directory
    if not os.path.isdir(new_path):
        return jsonify({'error': 'directory not found'}), 400
    global FPV_BASE
    FPV_BASE = new_path
    # persist to config file
    cfg = _load_config()
    if not isinstance(cfg, dict):
        cfg = {}
    cfg['FPV_BASE'] = FPV_BASE
    if not _save_config(cfg):
        return jsonify({'error': 'failed to save config'}), 500
    # Rebuild sessions cache
    try:
        _ = get_cached_sessions(FPV_BASE)
    except Exception as e:
        print('rebuild after FPV_BASE change failed:', e)
    return jsonify({'ok': True, 'FPV_BASE': FPV_BASE})


@app.before_request
def _check_revoked_users():
    # If a user's session has been revoked by admin, log them out on next request
    try:
        u = session.get('user')
        if u:
            with _active_lock:
                if u in REVOKED_USERS:
                    # remove from active and revoked lists and clear session user
                    try:
                        REVOKED_USERS.discard(u)
                    except Exception:
                        pass
                    try:
                        ACTIVE_USERS.discard(u)
                    except Exception:
                        pass
                    session.pop('user', None)
                    # don't redirect here; let route handlers handle unauthenticated flows
    except Exception:
        pass


@app.route('/api/admin/drones', methods=['GET', 'POST'])
def api_admin_drones():
    # admin-only
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error': 'admin required'}), 403
    _ensure_drone_dir()
    if request.method == 'GET':
        files = []
        try:
            for fn in os.listdir(DRONE_DIR):
                if os.path.isfile(os.path.join(DRONE_DIR, fn)) and os.path.splitext(fn)[1].lower() in ALLOWED_DRONE_EXT:
                    files.append(fn)
        except Exception:
            pass
        return jsonify({'drones': files})
    # POST: upload
    if 'file' not in request.files:
        return jsonify({'error':'file required'}), 400
    f = request.files['file']
    if not f or not f.filename:
        return jsonify({'error':'invalid file'}), 400
    filename = secure_filename(f.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_DRONE_EXT:
        return jsonify({'error':'only png and webp allowed'}), 400
    _ensure_drone_dir()
    dest = os.path.join(DRONE_DIR, filename)
    try:
        f.save(dest)
    except Exception as e:
        return jsonify({'error':'could not save file', 'detail': str(e)}), 500
    return jsonify({'ok': True, 'filename': filename})


@app.route('/api/admin/drones/<path:filename>', methods=['DELETE'])
def api_admin_delete_drone(filename):
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error': 'admin required'}), 403
    _ensure_drone_dir()
    fn = os.path.basename(filename)
    if os.path.splitext(fn)[1].lower() not in ALLOWED_DRONE_EXT:
        return jsonify({'error':'invalid filename'}), 400
    path = os.path.join(DRONE_DIR, fn)
    try:
        # ensure we don't delete the last drone image
        files = [f for f in os.listdir(DRONE_DIR) if os.path.isfile(os.path.join(DRONE_DIR, f)) and os.path.splitext(f)[1].lower() in ALLOWED_DRONE_EXT]
        if len(files) <= 1:
            return jsonify({'error': 'at least one drone image must remain'}), 400
        if os.path.exists(path):
            os.remove(path)
            return jsonify({'ok': True})
        return jsonify({'error':'not found'}), 404
    except Exception as e:
        return jsonify({'error':'could not delete', 'detail': str(e)}), 500


@app.route('/api/drones')
def api_drones_public():
    # public list of available drone images
    _ensure_drone_dir()
    out = []
    try:
        for fn in os.listdir(DRONE_DIR):
            if os.path.isfile(os.path.join(DRONE_DIR, fn)) and os.path.splitext(fn)[1].lower() in ALLOWED_DRONE_EXT:
                out.append(url_for('static', filename=f'login/drones/{fn}'))
    except Exception:
        pass
    # fallback to built-in images if none
    if not out:
        out = [
            url_for('static', filename='login/drone.png'),
            url_for('static', filename='login/drone_2.png')
        ]
    return jsonify({'drones': out})


@app.route('/api/admin/users', methods=['GET', 'POST'])
def api_admin_users():
    # admin-only
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error': 'admin required'}), 403
    _ensure_default_user()
    if request.method == 'GET':
        users = _load_users()
        # include permissions if present
        return jsonify({'users': [{ 'username': u, 'login_count': users[u].get('login_count',0), 'permissions': users[u].get('permissions', {}) } for u in users]})
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return jsonify({'error':'username and password required'}), 400
    users = _load_users()
    if username in users:
        return jsonify({'error':'user exists'}), 400
    # initialize permissions empty
    users[username] = { 'password_hash': generate_password_hash(password), 'login_count': 0, 'permissions': {} }
    ok = _save_users(users)
    if not ok:
        return jsonify({'error':'could not save users'}), 500
    return jsonify({'ok': True, 'username': username})


@app.route('/api/admin/users/<username>', methods=['DELETE'])
def api_admin_delete_user(username):
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error': 'admin required'}), 403
    uname = (username or '').strip()
    if not uname:
        return jsonify({'error':'username required'}), 400
    # protect configured admin account from deletion
    if uname == os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error':'cannot delete configured admin user'}), 400
    users = _load_users()
    if uname not in users:
        return jsonify({'error':'not found'}), 404
    users.pop(uname, None)
    ok = _save_users(users)
    if not ok:
        return jsonify({'error':'could not save users'}), 500
    return jsonify({'ok': True})


@app.route('/api/admin/users/<username>/password', methods=['POST'])
def api_admin_change_password(username):
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error': 'admin required'}), 403
    data = request.get_json(silent=True) or {}
    newpw = (data.get('password') or '').strip()
    if not newpw:
        return jsonify({'error':'password required'}), 400
    uname = (username or '').strip()
    users = _load_users()
    if uname not in users:
        return jsonify({'error':'not found'}), 404
    users[uname]['password_hash'] = generate_password_hash(newpw)
    ok = _save_users(users)
    if not ok:
        return jsonify({'error':'could not save users'}), 500
    return jsonify({'ok': True})


@app.route('/api/admin/users/<username>/permissions', methods=['POST'])
def api_admin_set_permissions(username):
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error': 'admin required'}), 403
    data = request.get_json(silent=True) or {}
    perms = data.get('permissions') or {}
    if not isinstance(perms, dict):
        return jsonify({'error':'permissions must be an object'}), 400
    uname = (username or '').strip()
    if not uname:
        return jsonify({'error':'username required'}), 400
    users = _load_users()
    if uname not in users:
        return jsonify({'error':'not found'}), 404
    users[uname]['permissions'] = perms
    ok = _save_users(users)
    if not ok:
        return jsonify({'error':'could not save users'}), 500
    return jsonify({'ok': True, 'username': uname, 'permissions': perms})

# ----------------- Create Sessions (Auto Session Sorter) -----------------

# Determine default sorter paths
AUTO_SORTER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'auto_session_sorter'))
SORTER_INPUT_DEFAULT = os.path.join(AUTO_SORTER_DIR, 'input')
FFPROBE_EXE = os.path.join(AUTO_SORTER_DIR, 'ffprobe.exe')

_sorter_jobs = {}
_sorter_lock = Lock()

def _get_sorter_input_dir():
    cfg = _load_config()
    d = None
    if isinstance(cfg, dict):
        d = cfg.get('AUTO_SORTER_INPUT')
    return d or SORTER_INPUT_DEFAULT

def _set_sorter_input_dir(path: str):
    cfg = _load_config()
    if not isinstance(cfg, dict):
        cfg = {}
    cfg['AUTO_SORTER_INPUT'] = path
    return _save_config(cfg)

def _human_size(n):
    try:
        n = float(n)
    except Exception:
        n = 0.0
    units = ['B','KB','MB','GB','TB']
    i = 0
    while n >= 1024 and i < len(units)-1:
        n /= 1024.0
        i += 1
    return f"{n:.1f} {units[i]}"

def _human_duration_sec(total_sec):
    try:
        total_sec = int(total_sec)
    except Exception:
        total_sec = 0
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"

def _is_video_file(fn: str):
    ext = os.path.splitext(fn)[1].lower()
    return ext in {'.mp4', '.mov', '.mkv', '.avi', '.m4v'}

def _probe_duration_seconds(path: str):
    # Prefer local ffprobe.exe if present; else rely on ffprobe in PATH
    exe = FFPROBE_EXE if os.path.exists(FFPROBE_EXE) else 'ffprobe'
    try:
        # Windows-safe call
        out = subprocess.check_output([
            exe,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            path
        ], stderr=subprocess.STDOUT, shell=False)
        s = out.decode('utf-8', errors='ignore').strip()
        return int(float(s)) if s else 0
    except Exception:
        return 0

@app.route('/create-sessions')
def create_sessions_page():
    # Require auth and permission
    current = session.get('user')
    if not current:
        return redirect(url_for('login', next=request.path))
    is_admin = (current == os.environ.get('FPVWEB_USER', 'admin'))
    allowed = False
    if is_admin:
        allowed = True
    else:
        try:
            users = _load_users() or {}
            perms = users.get(current, {}).get('permissions', {}) or {}
            allowed = bool(perms.get('create_sessions'))
        except Exception:
            allowed = False
    if not allowed:
        return redirect(url_for('index'))
    return render_template('create_sessions.html', sorter_input=_get_sorter_input_dir(), FPV_BASE=FPV_BASE)

@app.route('/api/sorter/config', methods=['GET', 'POST'])
def api_sorter_config():
    # auth required
    if not session.get('user'):
        return jsonify({'error': 'auth required'}), 401
    # only users with permission or admin can modify
    current = session.get('user')
    is_admin = (current == os.environ.get('FPVWEB_USER', 'admin'))
    if request.method == 'GET':
        return jsonify({'input_dir': _get_sorter_input_dir()})
    # POST
    data = request.get_json(silent=True) or {}
    new_dir = (data.get('input_dir') or '').strip()
    if not new_dir:
        return jsonify({'error': 'input_dir required'}), 400
    allowed = is_admin
    if not allowed:
        try:
            users = _load_users() or {}
            perms = users.get(current, {}).get('permissions', {}) or {}
            allowed = bool(perms.get('create_sessions'))
        except Exception:
            allowed = False
    if not allowed:
        return jsonify({'error': 'permission denied'}), 403
    if not os.path.isdir(new_dir):
        return jsonify({'error': 'directory not found'}), 400
    if not _set_sorter_input_dir(new_dir):
        return jsonify({'error': 'failed to save'}), 500
    return jsonify({'ok': True, 'input_dir': new_dir})

@app.route('/api/sorter/stats')
def api_sorter_stats():
    if not session.get('user'):
        return jsonify({'error': 'auth required'}), 401
    d = _get_sorter_input_dir()
    files = []
    total_size = 0
    total_dur = 0
    try:
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if os.path.isfile(p) and _is_video_file(fn):
                files.append(fn)
                try:
                    total_size += os.path.getsize(p)
                except Exception:
                    pass
                total_dur += _probe_duration_seconds(p)
    except Exception:
        pass
    return jsonify({
        'count': len(files),
        'total_size_bytes': int(total_size),
        'total_size_human': _human_size(total_size),
        'total_duration_seconds': int(total_dur),
        'total_duration_human': _human_duration_sec(total_dur),
        'files': files
    })

def _start_sorter_job(script_name: str):
    job_id = f"{int(time.time()*1000)}-{script_name}"
    log_lines = []
    status = {'running': True, 'exit_code': None}

    def runner():
        try:
            script_path = os.path.join(AUTO_SORTER_DIR, script_name)
            # Use current python executable
            # Provide a UTF-8 capable environment for the subprocess
            env = os.environ.copy()
            env.setdefault('PYTHONUTF8', '1')
            env.setdefault('PYTHONIOENCODING', 'utf-8')
            proc = subprocess.Popen([sys.executable, script_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=AUTO_SORTER_DIR, bufsize=1, text=True, encoding='utf-8', env=env)
            for line in proc.stdout or []:
                with _sorter_lock:
                    log_lines.append(line.rstrip('\n'))
            proc.wait()
            with _sorter_lock:
                status['running'] = False
                status['exit_code'] = proc.returncode
        except Exception as e:
            with _sorter_lock:
                log_lines.append(f"[error] {e}")
                status['running'] = False
                status['exit_code'] = -1

    import threading
    t = threading.Thread(target=runner, daemon=True)
    with _sorter_lock:
        _sorter_jobs[job_id] = {'lines': log_lines, 'status': status, 'script': script_name, 'done': False}
    t.start()
    return job_id

@app.route('/api/sorter/run', methods=['POST'])
def api_sorter_run():
    if not session.get('user'):
        return jsonify({'error': 'auth required'}), 401
    current = session.get('user')
    is_admin = (current == os.environ.get('FPVWEB_USER', 'admin'))
    allowed = is_admin
    if not allowed:
        try:
            users = _load_users() or {}
            perms = users.get(current, {}).get('permissions', {}) or {}
            allowed = bool(perms.get('create_sessions'))
        except Exception:
            allowed = False
    if not allowed:
        return jsonify({'error': 'permission denied'}), 403
    data = request.get_json(silent=True) or {}
    kind = (data.get('script') or '').strip().lower()
    if kind not in {'rename', 'session'}:
        return jsonify({'error': 'invalid script'}), 400
    script_file = '1._Auto_rename.py' if kind == 'rename' else '2._Auto_session.py'
    job_id = _start_sorter_job(script_file)
    return jsonify({'ok': True, 'job_id': job_id})

@app.route('/api/sorter/log/<job_id>')
def api_sorter_log(job_id):
    if not session.get('user'):
        return jsonify({'error': 'auth required'}), 401
    with _sorter_lock:
        job = _sorter_jobs.get(job_id)
        if not job:
            # Return stable shape so client polling stays robust
            return jsonify({'found': False, 'lines': [], 'status': {'running': False, 'exit_code': None}, 'script': None})
        # simple snapshot
        return jsonify({'found': True, 'lines': list(job['lines']), 'status': job['status'], 'script': job['script']})


@app.route('/api/sorter/jobs')
def api_sorter_jobs():
    # list known jobs (debugging)
    if not session.get('user'):
        return jsonify({'error': 'auth required'}), 401
    out = []
    with _sorter_lock:
        for jid, j in _sorter_jobs.items():
            out.append({'job_id': jid, 'script': j.get('script'), 'status': j.get('status')})
    return jsonify({'jobs': out})

# --- Authentication ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()
        # validate against file-backed users store
        _ensure_default_user()
        users = _load_users()
        u = users.get(username)
        if u and check_password_hash(u.get('password_hash',''), password):
            session['user'] = username
            with _active_lock:
                try:
                    ACTIVE_USERS.add(username)
                except Exception:
                    pass
            # increment login counter
            try:
                users[username]['login_count'] = int(users[username].get('login_count',0)) + 1
                _save_users(users)
            except Exception:
                pass
            # mark that the next page load should play the successful-login sound
            session['just_logged_in'] = True
            next_url = request.args.get('next') or url_for('index')
            return redirect(next_url)
        flash('Invalid credentials', 'danger')
    if session.get('user'):
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    try:
        u = session.get('user')
        if u:
            with _active_lock:
                try: ACTIVE_USERS.discard(u)
                except Exception: pass
    except Exception:
        pass
    session.pop('user', None)
    return redirect(url_for('login'))


@app.route('/api/admin/active-users')
def api_admin_active_users():
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error':'admin required'}), 403
    with _active_lock:
        return jsonify({'active': sorted(list(ACTIVE_USERS))})


@app.route('/api/admin/revoke-user', methods=['POST'])
def api_admin_revoke_user():
    if not session.get('user') or session.get('user') != os.environ.get('FPVWEB_USER', 'admin'):
        return jsonify({'error':'admin required'}), 403
    data = request.get_json(silent=True) or {}
    user = (data.get('username') or '').strip()
    if not user:
        return jsonify({'error':'username required'}), 400
    # mark revoked; next request from that user will be logged out
    with _active_lock:
        REVOKED_USERS.add(user)
        ACTIVE_USERS.discard(user)
    return jsonify({'ok': True})

# --- Share Link System ---
@app.route('/api/generate-share-link', methods=['POST'])
def generate_share_link_api():
    """Generate a shareable link for a video"""
    data = request.get_json()
    video_path = data.get('video_path')
    session_name = data.get('session_name')
    session_sub = data.get('session_sub')

    if not all([video_path, session_name, session_sub]):
        return jsonify({'error': 'Missing required parameters'}), 400

    # Generate unique link
    max_attempts = 10
    for _ in range(max_attempts):
        link_id = generate_share_link()
        if link_id not in SHARE_LINKS:
            break
    else:
        return jsonify({'error': 'Could not generate unique link'}), 500

    # Save the link
    save_share_link(link_id, video_path, session_name, session_sub)

    # Return the full URL
    share_url = request.host_url.rstrip('/') + url_for('shared_video', link_id=link_id)

    return jsonify({
        'link_id': link_id,
        'share_url': share_url,
        'video_path': video_path
    })

@app.route('/share/<link_id>')
def shared_video(link_id):
    """Display shared video page"""
    if link_id not in SHARE_LINKS:
        return "Share link not found or expired", 404

    link_data = SHARE_LINKS[link_id]
    video_path = link_data['video_path']
    session_name = link_data['session_name']
    session_sub = link_data['session_sub']

    # Try resolving the video path robustly. session_utils stores video paths
    # as relative paths from FPV_BASE (e.g. "SESSION/ SUB/ path/to/file.mp4").
    # Accept either that form or the older form where the saved video_path
    # was just a filename and should be resolved under session_name/sub.
    candidates = []
    try:
        vp = (video_path or '').lstrip('/\\')
        # Candidate: FPV_BASE + video_path (treat video_path as already relative to FPV_BASE)
        if vp:
            candidates.append(os.path.abspath(os.path.normpath(os.path.join(FPV_BASE, *vp.split('/')))))
        # Candidate: FPV_BASE / session_name / session_sub / video_path (older behavior)
        candidates.append(os.path.abspath(os.path.normpath(os.path.join(FPV_BASE, session_name, session_sub, vp))))
        # Candidate: FPV_BASE / session_name / session_sub / basename(video_path)
        candidates.append(os.path.abspath(os.path.normpath(os.path.join(FPV_BASE, session_name, session_sub, os.path.basename(vp)))))
    except Exception:
        candidates = []

    full_path = None
    base_abs = os.path.abspath(FPV_BASE)
    for c in candidates:
        if not c:
            continue
        # Ensure resolved path stays within FPV_BASE (prevent traversal)
        try:
            if not c.startswith(base_abs):
                continue
        except Exception:
            continue
        if os.path.exists(c):
            full_path = c
            break

    if not full_path:
        return "Video file not found", 404

    # For the template we want the path relative to FPV_BASE so the /media/ route works
    rel_for_template = os.path.relpath(full_path, FPV_BASE).replace('\\', '/')

    return render_template('shared_video.html',
                         link_id=link_id,
                         video_path=rel_for_template,
                         session_name=session_name,
                         session_sub=session_sub)


@app.route('/share/<link_id>/embed')
def shared_video_embed(link_id):
    """Minimal embeddable player for use as twitter/og player URL."""
    if link_id not in SHARE_LINKS:
        return "Share link not found or expired", 404

    link_data = SHARE_LINKS[link_id]
    video_path = link_data['video_path']
    session_name = link_data['session_name']
    session_sub = link_data['session_sub']

    # Resolve same as shared_video
    vp = (video_path or '').lstrip('/\\')
    candidates = [
        os.path.abspath(os.path.normpath(os.path.join(FPV_BASE, *vp.split('/')))) if vp else None,
        os.path.abspath(os.path.normpath(os.path.join(FPV_BASE, session_name, session_sub, vp))) if vp is not None else None,
        os.path.abspath(os.path.normpath(os.path.join(FPV_BASE, session_name, session_sub, os.path.basename(vp)))) if vp is not None else None,
    ]
    full_path = None
    base_abs = os.path.abspath(FPV_BASE)
    for c in candidates:
        if not c:
            continue
        try:
            if not c.startswith(base_abs):
                continue
        except Exception:
            continue
        if os.path.exists(c):
            full_path = c
            break

    if not full_path:
        return "Video file not found", 404

    rel_for_template = os.path.relpath(full_path, FPV_BASE).replace('\\', '/')
    rendered = render_template('shared_video_embed.html', video_path=rel_for_template)
    resp = make_response(rendered)
    # Allow the page to be embedded in iframes (for platforms that use the player URL)
    resp.headers['Content-Security-Policy'] = "frame-ancestors *"
    resp.headers['X-Frame-Options'] = 'ALLOWALL'
    return resp

@app.route('/api/share-links')
def list_share_links():
    """List all active share links (admin only)"""
    if not session.get('user'):
        return jsonify({'error': 'Authentication required'}), 401

    return jsonify({
        'links': [
            {
                'link_id': link_id,
                'share_url': request.host_url.rstrip('/') + url_for('shared_video', link_id=link_id),
                **link_data
            }
            for link_id, link_data in SHARE_LINKS.items()
        ]
    })

if __name__ == '__main__':
    app.run(debug=True)
