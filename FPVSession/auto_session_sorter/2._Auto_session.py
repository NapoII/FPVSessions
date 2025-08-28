import os
import re
import json
import shutil
from datetime import datetime, timedelta
import time
import subprocess
from pathlib import Path
import shutil as _shutil
import sys

# Ensure stdout is UTF-8 capable (Windows) to avoid UnicodeEncodeError on emoji prints
try:
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass

# === Configuration ===
INPUT_FOLDER = "/run/media/napo/10TB/FPV/WorkSpace/input"  # <-- input path
INPUT_FOLDER = r"H:\FPV\WorkSpace\input"

SESSIONS_FOLDER = "/run/media/napo/10TB/FPV/my_FPV/FPVSessions"  # <-- destination path
SESSIONS_FOLDER = r"H:\FPV\my_FPV\FPVSessions"

default_img_path = "/run/media/napo/10TB/FPV/WorkSpace/default_session_img.jpg"
default_img_path = r"H:\FPV\WorkSpace\default_session_img.jpg"


MAX_GAP_MINUTES = 70
DATETIME_PATTERN = r'^(\d{4}\.\d{2}\.\d{2}[._]\d{2}\.\d{2}\.\d{2})'

def create_and_sort_additional_folders(session_path):
    # Define subfolders and corresponding conditions
    subfolders = {
        "FPV_Camera": lambda f: "DJI-O4" in f,
        "Extern_Vison": lambda f: False,  # Placeholder if needed
        "Goggel_Vison": lambda f: "FPV-Goggel" in f,
        "IMG": lambda f: f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')),
        "Blackbox": lambda f: "BFL" in f,
    }

    # Create subfolders
    for folder in subfolders:
        os.makedirs(os.path.join(session_path, folder), exist_ok=True)

    # Move files based on condition
    for f in os.listdir(session_path):
        full_path = os.path.join(session_path, f)
        if os.path.isfile(full_path):
            for folder, condition in subfolders.items():
                if condition(f):
                    dest_path = os.path.join(session_path, folder, f)
                    shutil.move(full_path, dest_path)
                    break

def format_date(dt):
    return dt.strftime("%d.%b.%Y")

def format_time_full(dt):
    return dt.strftime("%H.%M.%S")

_FFPROBE_PATH = None
_FFPROBE_WARNED = False

def _get_ffprobe_path():
    """Resolve ffprobe executable path cross-platform. Returns None if not found."""
    global _FFPROBE_PATH
    if _FFPROBE_PATH is not None:
        return _FFPROBE_PATH

    candidates = []
    # 1) Local to this workspace
    try:
        here = Path(__file__).resolve().parent
        candidates.append(here / 'ffprobe.exe')
        candidates.append(here / 'ffprobe')
        # Workspace root fallback (..)
        candidates.append((here.parent / 'ffprobe.exe'))
        candidates.append((here.parent / 'ffprobe'))
    except Exception:
        pass

    # 2) Known path in this repo
    candidates.append(Path(r"H:\FPV\WorkSpace\ffprobe.exe"))
    candidates.append(Path(r"H:\FPV\WorkSpace\ffprobe"))

    # 3) Rely on PATH (use plain name)
    for name in ('ffprobe.exe', 'ffprobe'):
        candidates.append(Path(name))

    for c in candidates:
        try:
            if c and c.exists():
                _FFPROBE_PATH = str(c)
                return _FFPROBE_PATH
        except Exception:
            continue
    _FFPROBE_PATH = None
    return None

def get_video_duration_linux(file_path):
    """Get video duration using ffprobe. Returns seconds as float. Quietly returns 0 if ffprobe is missing."""
    global _FFPROBE_WARNED
    ffprobe_path = _get_ffprobe_path()
    if not ffprobe_path:
        if not _FFPROBE_WARNED:
            print("⚠️ ffprobe not found – video durations will be set to 0. Place ffprobe.exe in WorkSpace/.")
            _FFPROBE_WARNED = True
        return 0.0
    try:
        result = subprocess.run([
            ffprobe_path, '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)
        ], capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError) as e:
        # Keep quiet to avoid spam; treat as unknown duration
        pass
    return 0.0

def parse_duration_string(duration_str):
    try:
        parts = duration_str.split(":")
        if len(parts) == 3:
            h, m, s = map(int, parts)
            return h * 3600 + m * 60 + s
    except:
        pass
    return 0

def get_file_metadata(file_path):
    # Use file modification time as start time
    mtime = file_path.stat().st_mtime
    start_time = datetime.fromtimestamp(mtime)

    # Duration from metadata (using ffprobe when available)
    duration = 0
    if file_path.suffix.lower() in [".mp4", ".mov", ".avi"]:
        duration = get_video_duration_linux(file_path)

    # Calculate end time correctly
    end_time = start_time + timedelta(seconds=duration)

    return {
        "path": str(file_path),
        "date": format_date(start_time),
        "start_time": format_time_full(start_time),
        "end_time": format_time_full(end_time),
        "duration": round(duration / 60, 2),
        "raw_start": start_time,
        "raw_end": end_time
    }

# Adaptation idea:
# 1. Define a default image
# 2. When creating the JSON file, check if an image exists
# 3. If not: copy the default image into the IMG folder and include it in the JSON

def generate_flight_log(session_path):
    folder_name = os.path.basename(session_path)
    session_date = folder_name.split("_")[0]
    times = folder_name.split("_")[1].split("-")
    start_time_str = times[0]
    start_time_dt = datetime.strptime(f"{session_date}_{start_time_str}", "%Y.%m.%d_%H.%M.%S")

    subfolders = ["FPV_Camera", "Goggel_Vison"]
    best_folder = ""
    best_ext = ""
    best_files = []

    for folder in subfolders:
        full_folder = Path(session_path) / folder
        if not full_folder.exists():
            continue

        ext_count = {}
        files_by_ext = {}

        for f in full_folder.iterdir():
            if f.is_file():
                ext = f.suffix.lower()
                ext_count[ext] = ext_count.get(ext, 0) + 1
                files_by_ext.setdefault(ext, []).append(f)

        if ext_count:
            most_common_ext = max(ext_count, key=ext_count.get)
            if len(files_by_ext[most_common_ext]) > len(best_files):
                best_folder = folder
                best_ext = most_common_ext
                best_files = files_by_ext[most_common_ext]

    # Split detections
    large_files = [f for f in best_files if f.stat().st_size >= 3 * 1024 * 1024 * 1024]
    flight_starts = len(best_files) - len(large_files)

    # Flight time
    total_duration = 0.0
    file_entries = []
    for f in best_files:
        meta = get_file_metadata(f)
        total_duration += meta["duration"]
        file_entries.append({
            "type": best_folder.lower(),
            "original_path": meta["path"],
            "new_name": os.path.basename(meta["path"]),
            "date": meta["date"],
            "start_time": meta["start_time"],
            "end_time": meta["end_time"],
            "duration_min": meta["duration"]
        })

    # Add IMG and Blackbox (including copying default image into IMG if empty)
    import sys
    if sys.platform.startswith("win"):
        default_img_path = Path(r"H:\FPV\WorkSpace\default_session_img.jpg")
    else:
        default_img_path = Path("/run/media/napo/10TB/FPV/WorkSpace/default_session_img.jpg")
    for folder in ["IMG", "Blackbox"]:
        full_folder = Path(session_path) / folder
        full_folder.mkdir(exist_ok=True)

        folder_files = list(full_folder.glob("*"))
        if folder == "IMG" and not folder_files:
            # Copy default image without noisy debug prints
            target_default_img = full_folder / default_img_path.name
            if default_img_path.exists():
                shutil.copy2(default_img_path, target_default_img)
                folder_files = [target_default_img]

        for f in folder_files:
            if f.is_file():
                meta = get_file_metadata(f)
                file_entries.append({
                    "type": folder.lower(),
                    "original_path": meta["path"],
                    "new_name": os.path.basename(meta["path"]),
                    "date": meta["date"],
                    "start_time": meta["start_time"],
                    "end_time": meta["end_time"],
                    "duration_min": meta["duration"]
                })

    # Compute end time from start time + total flight time
    end_time_dt = start_time_dt + timedelta(minutes=total_duration)
    end_time_str = end_time_dt.strftime("%H.%M.%S")

# Flight log template
    log_text = f"""# Flight Log
--------------------------------------------
# Date: {session_date}
# Location:
# Start Time: {start_time_str}
# End Time: {end_time_str}
# Pilot:
# Co-pilot:
--------------------------------------------
# Flight starts: {flight_starts}
# Total flight time: {round(total_duration, 2)} min
-------------------------------------------
# Short report:
#
#
# Observations:
#
#
"""

    txt_path = Path(session_path) / f"{folder_name}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(log_text)

    json_data = {
        "session": {
            "session_date": session_date,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "location": "",
            "pilot": "",
            "co_pilot": "",
            "flight_count": flight_starts,
            "total_flight_time_min": round(total_duration, 2),
            "files": file_entries
        }
    }
    json_path = Path(session_path) / f"{folder_name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4)

### 📝 Save metadata


# === Hilfsfunktionen ===
def timestamp():
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

def log(msg):
    global collected_logs
    collected_logs.append(f"{timestamp()} 📝 {msg}")

# Global for progress and logs
collected_logs = []

def update_progress(status_line):
    """Windows-friendly single-line progress using carriage return and width-aware padding."""
    try:
        width = _shutil.get_terminal_size(fallback=(100, 20)).columns
    except Exception:
        width = 100
    # Reserve last column for carriage return safety
    maxlen = max(10, width - 1)
    if len(status_line) > maxlen:
        # Ellipsize
        status_line = status_line[: maxlen - 1] + "…"
    # Pad to clear remnants of previous longer line
    padded = status_line.ljust(maxlen)
    print("\r" + padded, end="", flush=True)

def copy_file_with_progress(src, dst, processed_files, total_files, start_time, filename):
    file_size = os.path.getsize(src)
    copied = 0
    chunk_size = 1024 * 1024  # 1 MB chunks
    last_update = 0.0
    start_file = time.time()

    spinner = ['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏']
    with open(src, 'rb') as fsrc:
        with open(dst, 'wb') as fdst:
            while True:
                chunk = fsrc.read(chunk_size)
                if not chunk:
                    break
                fdst.write(chunk)
                copied += len(chunk)

                # Throttle UI updates to ~15 Hz to reduce flicker
                now = time.time()
                if now - last_update < 1/15:
                    continue
                last_update = now

                # Overall stats
                current_processed = processed_files + 1  # copying one file
                elapsed_total = (datetime.now() - start_time).total_seconds()
                avg_sec_per_file = elapsed_total / current_processed if current_processed > 0 else 0
                remaining = total_files - current_processed
                est_remaining_sec = max(0.0, avg_sec_per_file * remaining)
                est_end = datetime.now() + timedelta(seconds=est_remaining_sec)

                # File stats
                pct = (copied / file_size) * 100 if file_size else 100.0
                mb_copied = copied / (1024 * 1024)
                mb_total = file_size / (1024 * 1024) if file_size else 0
                elapsed_file = now - start_file
                speed = (mb_copied / elapsed_file) if elapsed_file > 0 else 0
                mbps = speed * 8.0
                total_pct = ((processed_files + pct/100.0) / max(1, total_files)) * 100.0
                spin = spinner[int(now * 10) % len(spinner)]

                # Build concise, informative status line
                status = (
                    f"{spin} {current_processed}/{total_files} {total_pct:5.1f}% | "
                    f"{mb_copied:.1f}/{mb_total:.1f}MB {pct:5.1f}% @ {speed:.1f}MB/s {mbps:.0f}Mbit/s | "
                    f"eta {est_end.strftime('%H:%M:%S')} | {filename}"
                )
                update_progress(status)
    # End of file copy - print final line and newline
    current_processed = processed_files + 1
    elapsed_total = (datetime.now() - start_time).total_seconds()
    avg_sec_per_file = elapsed_total / current_processed if current_processed > 0 else 0
    remaining = total_files - current_processed
    est_remaining_sec = max(0.0, avg_sec_per_file * remaining)
    est_end = datetime.now() + timedelta(seconds=est_remaining_sec)
    done_line = (
        f"✅ {current_processed}/{total_files} | eta {est_end.strftime('%H:%M:%S')} | {avg_sec_per_file:.2f}s/file | {filename} done"
    )
    print("\r" + done_line)

def find_all_files(folder):
    log("Searching for all files with valid datetime format in the filename...")
    files = []
    for root, _, filenames in os.walk(folder):
        for f in filenames:
            if parse_datetime_from_filename(f):
                files.append(os.path.join(root, f))
    log(f"Found valid files: {len(files)}")
    return files


def create_and_sort_additional_folders(session_path):
    # Define subfolders and corresponding conditions
    subfolders = {
        "FPV_Camera": lambda f: "DJI-O4" in f,
        "Extern_Vison": lambda f: False,  # Placeholder if needed
        "Goggel_Vison": lambda f: "FPV-Goggel" in f,
        "IMG": lambda f: f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')),
        "Blackbox": lambda f: "BFL" in f,
    }

    # Create subfolders
    for folder in subfolders:
        os.makedirs(os.path.join(session_path, folder), exist_ok=True)

    # Move files based on condition
    for f in os.listdir(session_path):
        full_path = os.path.join(session_path, f)
        if os.path.isfile(full_path):
            for folder, condition in subfolders.items():
                if condition(f):
                    dest_path = os.path.join(session_path, folder, f)
                    shutil.move(full_path, dest_path)
                    break


def parse_datetime_from_filename(filename):
    match = re.match(DATETIME_PATTERN, os.path.basename(filename))
    if match:
        dt_str = match.group(1).replace(".", ".", 2).replace(".", ":", 2).replace(".", ":", 1)
        try:
            return datetime.strptime(match.group(1), "%Y.%m.%d.%H.%M.%S")
        except ValueError:
            try:
                return datetime.strptime(match.group(1), "%Y.%m.%d_%H.%M.%S")
            except ValueError:
                return None
    return None

def group_files_by_session(file_list, max_gap_minutes=60):
    log("Grouping files into sessions...")
    files_with_time = []
    for path in file_list:
        dt = parse_datetime_from_filename(path)
        if dt:
            files_with_time.append((dt, path))
    files_with_time.sort()

    sessions = []
    current_session = []
    last_time = None

    for dt, path in files_with_time:
        if not last_time or (dt - last_time <= timedelta(minutes=max_gap_minutes)):
            current_session.append({'timestamp': dt.isoformat(), 'path': path})
        else:
            if current_session:
                sessions.append(current_session)
            current_session = [{'timestamp': dt.isoformat(), 'path': path}]
        last_time = dt

    if current_session:
        sessions.append(current_session)
    log(f"Created sessions: {len(sessions)}")
    return sessions

def session_time_overlap(start1, end1, start2, end2):
    return max(start1, start2) <= min(end1, end2)

def session_folder_name(start_time):
    return f"{start_time:%Y.%m.%d}_FPVSession"

def full_session_name(start_time, end_time):
    return f"{start_time:%Y.%m.%d}_{start_time:%H.%M.%S}-{end_time:%H.%M.%S}_FPVSession"

def find_or_create_session_folder(base_path, session_start, session_end):
    base_folder = os.path.join(base_path, session_folder_name(session_start))
    os.makedirs(base_folder, exist_ok=True)

    for name in os.listdir(base_folder):
        session_path = os.path.join(base_folder, name)
        if os.path.isdir(session_path):
            match = re.match(r'.*_(\d{2}\.\d{2}\.\d{2})-(\d{2}\.\d{2}\.\d{2})', name)
            if match:
                existing_start = datetime.strptime(f"{session_start:%Y.%m.%d}_{match.group(1)}", "%Y.%m.%d_%H.%M.%S")
                existing_end = datetime.strptime(f"{session_start:%Y.%m.%d}_{match.group(2)}", "%Y.%m.%d_%H.%M.%S")
                if session_time_overlap(existing_start, existing_end, session_start, session_end):
                    log(f"Existing session found: {session_path}")
                    return session_path

    new_folder_name = full_session_name(session_start, session_end)
    new_folder_path = os.path.join(base_folder, new_folder_name)
    os.makedirs(new_folder_path)
    log(f"Created new session: {new_folder_path}")
    return new_folder_path

def copy_files_to_session(session_path, session_files, processed_files, total_files, start_time):
    log(f"Copying {len(session_files)} file(s) to {session_path}...")
    for i, f in enumerate(session_files, 1):
        filename = os.path.basename(f['path'])
        dest_path = os.path.join(session_path, filename)
        if not os.path.exists(dest_path):
            copy_file_with_progress(f['path'], dest_path, processed_files + i - 1, total_files, start_time, filename)
        else:
            log(f"⚠️ File already exists, skipped: {filename}")
            # Still update progress
            current_processed = processed_files + i
            elapsed = datetime.now() - start_time
            elapsed_sec = elapsed.total_seconds()
            avg_sec_per_file = elapsed_sec / current_processed if current_processed > 0 else 0
            remaining = total_files - current_processed
            est_remaining_sec = avg_sec_per_file * remaining
            est_end = datetime.now() + timedelta(seconds=est_remaining_sec)

            status = (
                f"⏭️ {current_processed}/{total_files} | eta {est_end.strftime('%H:%M:%S')} | {avg_sec_per_file:.2f}s/file | Skipped {filename}"
            )
            print(status)
    print()  # extra break after a session

# === Main flow ===
if __name__ == "__main__":
    log("🚀 Starting session organization")
    all_files = find_all_files(INPUT_FOLDER)
    sessions = group_files_by_session(all_files, MAX_GAP_MINUTES)

    # Calculate total files
    total_files = sum(len(session) for session in sessions)
    processed_files = 0
    start_time = datetime.now()

    for idx, session in enumerate(sessions, 1):
        log(f"🔢 Processing session {idx}/{len(sessions)}")
        start_time_session = datetime.fromisoformat(session[0]['timestamp'])
        end_time_session = datetime.fromisoformat(session[-1]['timestamp'])
        session_path = find_or_create_session_folder(SESSIONS_FOLDER, start_time_session, end_time_session)
        copy_files_to_session(session_path, session, processed_files, total_files, start_time)
        processed_files += len(session)
        create_and_sort_additional_folders(session_path)
        generate_flight_log(session_path)

        # Print collected logs after each session
        for log_msg in collected_logs:
            print(log_msg)
        collected_logs.clear()
        print()  # Extra line break

    log("✅ All sessions were successfully organized and copied.")
    # Print any remaining logs
    for log_msg in collected_logs:
        print(log_msg)
    print()  # Final break
