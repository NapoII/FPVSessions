import os
import time
from datetime import datetime
import threading
import json
try:
    from .thumbnail_utils import generate_thumbnail
except Exception:
    # script fallback
    from flask_app.utils.thumbnail_utils import generate_thumbnail

def _extract_session_date(session_folder: str, sub_folder: str) -> str:
    """Extract ISO date (YYYY-MM-DD) from folder names like '2025.04.27_FPVSession'."""
    for name in (session_folder, sub_folder):
        try:
            prefix = name.split('_', 1)[0]
            parts = prefix.split('.')
            if len(parts) >= 3:
                y, m, d = parts[0:3]
                dt = datetime(int(y), int(m), int(d))
                return dt.strftime('%Y-%m-%d')
        except Exception:
            continue
    return ''

def _parse_session_times(session_folder: str, sub_folder: str):
    """Parse start/end times from sub-folder like 'YYYY.MM.DD_HH.MM.SS-HH.MM.SS_FPVSession'."""
    try:
        date_part = session_folder.split('_', 1)[0]
        if len(date_part.split('.')) < 3:
            date_part = sub_folder.split('_', 1)[0]
        y, m, d = map(int, date_part.split('.')[:3])
        rest = sub_folder.split('_', 1)[1] if '_' in sub_folder else ''
        times = rest.split('_', 1)[0] if rest else ''
        start_t, end_t = (times.split('-') + ['',''])[:2]
        def parse_time(t):
            try:
                hh, mm, ss = map(int, t.split('.')[:3])
                return hh, mm, ss
            except Exception:
                return 0, 0, 0
        sh, sm, ss = parse_time(start_t)
        eh, em, es = parse_time(end_t)
        start_dt = datetime(y, m, d, sh, sm, ss)
        end_dt = datetime(y, m, d, eh, em, es)
        if end_dt < start_dt:
            end_dt = start_dt
        duration_min = int((end_dt - start_dt).total_seconds() // 60)
        weekday_map = ['Mo','Di','Mi','Do','Fr','Sa','So']
        weekday = weekday_map[start_dt.weekday()]
        human_date = f"{d:02d}.{m:02d}.{y}"
        time_range = f"{sh:02d}:{sm:02d}–{eh:02d}:{em:02d}"
        return {
            'start_dt_iso': start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'end_dt_iso': end_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'duration_min': duration_min,
            'weekday': weekday,
            'human_date': human_date,
            'time_range': time_range,
            'sort_key': (start_dt.strftime('%Y-%m-%d'), start_dt.strftime('%H:%M:%S'))
        }
    except Exception:
        return {
            'start_dt_iso': '', 'end_dt_iso': '', 'duration_min': None,
            'weekday': '', 'human_date': '', 'time_range': '', 'sort_key': ('','')
        }

def build_date_index(sessions):
    """Build a mapping date->list(sessions) and a sorted set of months present (YYYY-MM)."""
    date_map = {}
    months = set()
    for s in sessions:
        dt = s.get('date', '')
        if not dt:
            continue
        date_map.setdefault(dt, []).append(s)
        months.add(dt[:7])
    return date_map, sorted(months)

_CACHE = {
    'sessions': None,
    'last_built': 0.0,
    'building': False,
    'progress': 0,
}
_BG_JOB_RUNNING = False

def _scan_sessions(FPV_BASE: str, generate_thumbs: bool) -> list:
    sessions = []
    # Guard: if base directory doesn't exist, return empty list gracefully
    try:
        if not FPV_BASE or not os.path.isdir(FPV_BASE):
            # Keep cache progress coherent for UI
            _CACHE['progress'] = 100
            print("⚠️ Sessions base not found:", FPV_BASE)
            return []
    except Exception:
        return []
    total_videos = 0
    thumb_tasks = []

    # Sammle Thumbnail-Aufgaben
    for session_folder in sorted(os.listdir(FPV_BASE)):
        session_path = os.path.join(FPV_BASE, session_folder)
        if os.path.isdir(session_path):
            for sub in sorted(os.listdir(session_path)):
                sub_path = os.path.join(session_path, sub)
                if os.path.isdir(sub_path):
                    img_dir = os.path.join(sub_path, 'IMG')
                    if not os.path.exists(img_dir):
                        os.makedirs(img_dir)
                    for root, dirs, files in os.walk(sub_path):
                        for f in files:
                            if f.lower().endswith(('.mp4', '.mov')):
                                base_name = os.path.splitext(os.path.basename(f))[0]
                                thumb_name = f"{base_name}_thumb.jpg"
                                thumb_path = os.path.join(img_dir, thumb_name)
                                abs_video = os.path.join(root, f)
                                if not os.path.exists(thumb_path):
                                    thumb_tasks.append((abs_video, thumb_path))
                                total_videos += 1

    # Optional: Thumbs generieren
    if generate_thumbs and thumb_tasks:
        print(f"\n🖼️ Es werden {len(thumb_tasks)} neue Thumbnails generiert (von {total_videos} Videos)...")
        start = time.time()
        for idx, (abs_video, thumb_path) in enumerate(thumb_tasks, 1):
            # Update progress during thumbnail generation (10% to 80%)
            progress = 10 + int((idx / len(thumb_tasks)) * 70)
            _CACHE['progress'] = progress

            ok = generate_thumbnail(abs_video, thumb_path)
            now = time.time()
            elapsed = now - start
            avg = elapsed / idx if idx else 0.0
            remaining = len(thumb_tasks) - idx
            eta_secs = avg * remaining
            end_ts = start + avg * len(thumb_tasks) if avg > 0 else now
            line = (
                f"\r⚙️ {idx:>3} / {len(thumb_tasks)} Thumbs ({progress}%) | "
                f"🕒 Start: {time.strftime('%H:%M:%S', time.localtime(start))} | "
                f"⏱️ Elapsed: {elapsed:.1f}s | "
                f"⏲️ Avg/Thumb: {avg:.2f}s | "
                f"⏳ ETA: {eta_secs:.1f}s | "
                f"🏁 End: {time.strftime('%H:%M:%S', time.localtime(end_ts))} | "
                f"{'✅' if ok else '❌'} {os.path.basename(abs_video)}"
            )
            print(line, end='', flush=True)
        print()
        _CACHE['progress'] = 80

    # Sessions aufbauen
    for session_folder in sorted(os.listdir(FPV_BASE)):
        session_path = os.path.join(FPV_BASE, session_folder)
        if os.path.isdir(session_path):
            for sub in sorted(os.listdir(session_path)):
                sub_path = os.path.join(session_path, sub)
                if os.path.isdir(sub_path):
                    img_dir = os.path.join(sub_path, 'IMG')
                    meta_path = os.path.join(sub_path, '.fpvweb_meta.json')
                    _times = _parse_session_times(session_folder, sub)
                    session = {
                        'name': session_folder,
                        'sub': sub,
                        'videos': [],
                        'images': [],
                        'logs': [],
                        'goggles': [],
                        'blackbox': [],
                        'meta': [],
                        'thumbnails': [],
                        'preview_video': None,
                        'preview_thumb': None,
                        'date': _extract_session_date(session_folder, sub),
                        'times': _times,
                        'video_count': 0,
                        'image_count': 0,
                        'log_count': 0,
                        'blackbox_count': 0,
                        'tags': []
                    }

                    # Tags laden
                    try:
                        if os.path.exists(meta_path):
                            with open(meta_path, 'r', encoding='utf-8') as f:
                                meta = json.load(f)
                                tags = meta.get('tags', [])
                                if isinstance(tags, list):
                                    norm = []
                                    seen = set()
                                    for t in tags:
                                        v = str(t).strip().lower()
                                        if v and v not in seen:
                                            seen.add(v)
                                            norm.append(v)
                                    session['tags'] = norm
                    except Exception:
                        pass

                    min_size = None
                    min_video_rel = None
                    thumb_by_video = {}

                    for root, dirs, files in os.walk(sub_path):
                        for f in files:
                            rel_path = os.path.relpath(os.path.join(root, f), FPV_BASE).replace('\\','/')
                            if f.lower().endswith(('.mp4', '.mov')):
                                session['videos'].append(rel_path)
                                session['video_count'] += 1
                                base_name = os.path.splitext(os.path.basename(f))[0]
                                thumb_name = f"{base_name}_thumb.jpg"
                                thumb_path = os.path.join(img_dir, thumb_name)
                                thumb_rel = os.path.relpath(thumb_path, FPV_BASE).replace('\\','/')
                                session['thumbnails'].append({'video': rel_path, 'thumb': thumb_rel})
                                thumb_by_video[rel_path] = thumb_rel
                                try:
                                    abs_video = os.path.join(root, f)
                                    size = os.path.getsize(abs_video)
                                    if min_size is None or size < min_size:
                                        min_size = size
                                        min_video_rel = rel_path
                                except Exception:
                                    pass
                            elif f.lower().endswith(('.png', '.jpg', '.jpeg')):
                                session['images'].append(rel_path)
                                session['image_count'] += 1
                            elif f.lower().endswith('.bfl'):
                                session['blackbox'].append(rel_path)
                                session['blackbox_count'] += 1
                            elif f.lower().endswith('.txt'):
                                session['logs'].append(rel_path)
                                session['log_count'] += 1
                            elif f.lower().endswith('.json'):
                                session['meta'].append(rel_path)
                            else:
                                if 'goggel' in f.lower():
                                    session['goggles'].append(rel_path)

                    # set preview video and preferred thumbnail
                    if min_video_rel:
                        session['preview_video'] = min_video_rel
                        if min_video_rel in thumb_by_video:
                            session['preview_thumb'] = thumb_by_video[min_video_rel]
                        elif session['thumbnails']:
                            session['preview_thumb'] = session['thumbnails'][0]['thumb']
                    sessions.append(session)

    # Nach Datum und Startzeit absteigend sortieren
    sessions.sort(key=lambda s: (s.get('date',''), s.get('times',{}).get('sort_key', ('',''))), reverse=True)
    return sessions

def get_meta_path(FPV_BASE: str, session_folder: str, sub: str) -> str:
    return os.path.join(FPV_BASE, session_folder, sub, '.fpvweb_meta.json')

def get_session_tags(FPV_BASE: str, session_folder: str, sub: str) -> list:
    path = get_meta_path(FPV_BASE, session_folder, sub)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                tags = data.get('tags', [])
                if isinstance(tags, list):
                    norm = []
                    seen = set()
                    for t in tags:
                        v = str(t).strip().lower()
                        if v and v not in seen:
                            seen.add(v)
                            norm.append(v)
                    return norm
    except Exception:
        return []
    return []

def save_session_tags(FPV_BASE: str, session_folder: str, sub: str, tags: list) -> list:
    path = get_meta_path(FPV_BASE, session_folder, sub)
    norm = []
    seen = set()
    for t in (tags or []):
        v = str(t).strip().lower()
        if v and v not in seen:
            seen.add(v)
            norm.append(v)
    data = {'tags': norm}
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print('❌ Fehler beim Speichern der Tags:', e)

    # Cache aktualisieren
    if _CACHE.get('sessions'):
        for s in _CACHE['sessions']:
            if s['name'] == session_folder and s['sub'] == sub:
                s['tags'] = data['tags']
                break
    return data['tags']

def refresh_sessions(FPV_BASE: str, generate_thumbs: bool = False):
    if _CACHE['building']:
        return
    _CACHE['building'] = True
    _CACHE['progress'] = 0
    try:
        print("\n🗂️ (Re)Build Sessions Index ...")
        _CACHE['progress'] = 10
        sessions = _scan_sessions(FPV_BASE, generate_thumbs)
        _CACHE['progress'] = 90
        _CACHE['sessions'] = sessions
        _CACHE['last_built'] = time.time()
        _CACHE['progress'] = 100
        print("✅ Index bereit! Sessions:", len(sessions))
    finally:
        _CACHE['building'] = False

def get_cached_sessions(FPV_BASE: str, max_age_sec: int = 600):
    now = time.time()
    if not _CACHE['sessions'] or (now - _CACHE['last_built'] > max_age_sec and not _CACHE['building']):
        refresh_sessions(FPV_BASE, generate_thumbs=False)
    return _CACHE['sessions'] or []

def start_background_thumb_job(FPV_BASE: str):
    global _BG_JOB_RUNNING
    if _BG_JOB_RUNNING:
        return
    def _job():
        try:
            refresh_sessions(FPV_BASE, generate_thumbs=True)
        except Exception as e:
            print("❌ Hintergrund-Job Fehler:", e)
    t = threading.Thread(target=_job, daemon=True)
    t.start()
    _BG_JOB_RUNNING = True
