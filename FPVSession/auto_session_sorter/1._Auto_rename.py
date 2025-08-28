import os
import time
from datetime import datetime, timezone, timedelta
import re
import filecmp
import hashlib
from collections import defaultdict
import subprocess
from pathlib import Path
import shutil
import sys

# Ensure stdout is UTF-8 capable to allow printing emojis on Windows consoles
try:
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass

EXCLUDED_FILES_FROM_RENAMING = {"default_session_img.jpg"}


# Format functions
def format_date(dt):
    return dt.strftime("%d.%b.%Y")

def format_time_full(dt):
    return dt.strftime("%H.%M.%S")

def get_video_duration_linux(file_path):
    """Get video duration using ffprobe (Linux/portable). Returns seconds as float."""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)
        ], capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
        print(f"⚠️ Error retrieving video duration from {file_path}: {e}")
    return 0

def get_file_metadata(file_path):
    # Use file modification time as start time
    mtime = file_path.stat().st_mtime
    start_time = datetime.fromtimestamp(mtime)

    # Duration from metadata (using ffprobe when available)
    duration = 0
    if file_path.suffix.lower() in [".mp4", ".mov", ".avi"]:
        duration = get_video_duration_linux(file_path)

    # Calculate end time
    end_time = start_time + timedelta(seconds=duration)

    return {
        "path": file_path,
        "date": format_date(start_time),
        "start_time": format_time_full(start_time),
        "end_time": format_time_full(end_time),
        "duration": round(duration / 60, 2),
        "raw_start": start_time,
        "raw_end": end_time
    }

# === CONFIGURATION ===
script_dir = os.path.dirname(os.path.abspath(__file__))

# === HASH-BASED DUPLICATE DETECTION WITH PREFILTER ===
def get_file_hash(filepath, chunk_size=1024*1024):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()
def find_and_delete_duplicates(directory):
    print("\n🔍 Starting duplicate check...")
    size_map = defaultdict(list)
    hashes = defaultdict(list)

    all_files = [os.path.join(root, name)
                 for root, _, files in os.walk(directory)
                 for name in files]

    # Group by file size
    for path in all_files:
        try:
            size = os.path.getsize(path)
            size_map[size].append(path)
        except Exception as e:
            print(f"⚠️ Error getting size of {path}: {e}")

    total_groups = sum(1 for paths in size_map.values() if len(paths) > 1)
    group_index = 0
    deleted = 0

    # Only hash files that share the same size
    for size, paths in size_map.items():
        if len(paths) < 2:
            continue

        group_index += 1
        print(f"⏳ [{group_index}/{total_groups}] Checking group with size {size} bytes", end='\r')

        for path in paths:
            try:
                file_hash = get_file_hash(path)
                hashes[file_hash].append(path)
            except Exception as e:
                print(f"⚠️ Error hashing {path}: {e}")

    print("\n✅ Duplicate check completed.")
    EXCLUDED_DUPLICATE_FILES = {"default_session_img.jpg"}

    for paths in hashes.values():
        if len(paths) > 1:
            for dup_path in paths[1:]:
                if os.path.basename(dup_path).lower() in EXCLUDED_DUPLICATE_FILES:
                    print(f"⛔ File excluded from duplicate deletion: {dup_path}")
                    continue
                try:
                    os.remove(dup_path)
                    print(f"🗑️ Deleted duplicate: {dup_path}")
                    deleted += 1
                except Exception as e:
                    print(f"⚠️ Error deleting {dup_path}: {e}")


    print(f"\n📦 Total duplicates deleted: {deleted}")
    return deleted

def get_mov_creation_date(filepath):
    try:
        output = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "format_tags=creation_time", "-of", "default=noprint_wrappers=1:nokey=1", filepath],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        if output:
            dt = datetime.fromisoformat(output.replace('Z', '+00:00'))
            return dt.astimezone().replace(tzinfo=None)
    except Exception as e:
        print(f"⚠️ Error reading metadata from {filepath}: {e}")
        return None
# === PROCESS ALL FILES IN DIRECTORY ===
print("🚀 Starting file renaming...")
used_filenames = set()
all_files = [os.path.join(root, name)
             for root, _, files in os.walk(script_dir)
             for name in files]
total_files = len(all_files)
umbenannt = 0
gelöscht_mp4 = 0

for idx, filepath in enumerate(all_files):
    # Skip excluded files
    if os.path.basename(filepath).lower() in EXCLUDED_FILES_FROM_RENAMING:
        print(f"⏭️ Skipping excluded file: {filepath}")
        continue

    filename = os.path.basename(filepath)
    print(f"🔄 [{idx+1}/{total_files}] Processing: {filename}", end='\r')
    lower_filename = filename.lower()

    if not os.path.isfile(filepath):
        continue

    mod_time = os.path.getmtime(filepath)
    mod_datetime = datetime.fromtimestamp(mod_time)
    date_prefix = mod_datetime.strftime("%Y.%m.%d_%H.%M.%S")
    dir_of_file = os.path.dirname(filepath)

    # BFL files (blackbox)
    if lower_filename.endswith('.bfl'):
        match = re.search(r"(\d+)", filename)
        number_part = match.group(1).zfill(5) if match else '00000'
        base_name = f"{date_prefix}_FPV_Blackbox_{number_part}"
        new_filename = f"{base_name}.BFL"
        new_file_path = os.path.join(dir_of_file, new_filename)

        if new_filename.lower() in used_filenames or os.path.exists(new_file_path):
            if os.path.exists(new_file_path) and filecmp.cmp(filepath, new_file_path, shallow=False):
                os.remove(filepath)
                print(f"🗑️ Duplicate file '{filename}' was removed (identical to '{new_filename}')")
                gelöscht_mp4 += 1
                continue
            else:
                print(f"⚠️ Conflict: file with number {number_part} already exists but is not identical.")
                continue

        used_filenames.add(new_filename.lower())
        os.rename(filepath, new_file_path)
        os.utime(new_file_path, (mod_time, mod_time))
        umbenannt += 1
        print(f"✅ File '{filename}' renamed to: {new_filename}")

    # FPV-Goggel MP4 files
    elif lower_filename.endswith('.mp4') and 'goggel_vison' in lower_filename:
        metadata = get_file_metadata(Path(filepath))
        creation_date = metadata.get('raw_start')
        if creation_date:
            date_prefix = creation_date.strftime('%Y.%m.%d_%H.%M.%S')
        else:
            date_prefix = 'Unknown_Date'

        base_name = f"{date_prefix}_FPV-Goggel"
        new_filename = f"{base_name}.MP4"
        counter = 1
        while new_filename.lower() in used_filenames or os.path.exists(os.path.join(dir_of_file, new_filename)):
            new_filename = f"{base_name}_{counter}.MP4"
            counter += 1

        used_filenames.add(new_filename.lower())
        new_file_path = os.path.join(dir_of_file, new_filename)
        os.rename(filepath, new_file_path)
        os.utime(new_file_path, (mod_time, mod_time))
        umbenannt += 1
        print(f"✅ File '{filename}' renamed to: {new_filename}")

    # MOV files starting with DJI_
    elif lower_filename.endswith('.mov') and filename.startswith('DJI_'):
        creation_date = get_mov_creation_date(filepath)
        if creation_date:
            date_prefix = creation_date.strftime('%Y.%m.%d_%H.%M.%S')

        match = re.match(r"DJI_(\d+)(?:_1)?\.MOV", filename, re.IGNORECASE)
        if match:
            file_num = match.group(1)
            base_name = f"{date_prefix}_{file_num}_FPV-Goggel"
            new_filename = f"{base_name}.MOV"
            counter = 1
            while new_filename.lower() in used_filenames or os.path.exists(os.path.join(dir_of_file, new_filename)):
                new_filename = f"{base_name}_{counter}.MOV"
                counter += 1

            used_filenames.add(new_filename.lower())
            new_file_path = os.path.join(dir_of_file, new_filename)
            os.rename(filepath, new_file_path)
            os.utime(new_file_path, (mod_time, mod_time))
            umbenannt += 1
            print(f"✅ File '{filename}' renamed to: {new_filename}")

    # DJI MP4s
    elif lower_filename.endswith('.mp4') and filename.startswith('DJI_'):
        creation_date = get_mov_creation_date(filepath)
        if creation_date:
            date_prefix = creation_date.strftime('%Y.%m.%d_%H.%M.%S')
        else:
            date_prefix = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y.%m.%d_%H.%M.%S')

        match = re.match(r"DJI_(\d+)_\d+_D\.MP4", filename, re.IGNORECASE)
        print(f"Match: {match}")
        if match:
            file_num = match.group(1)
            base_name = f"{date_prefix}_{file_num}_DJI-O4"
            new_filename = f"{base_name}.MP4"
            print(f"New name: {new_filename}")

            counter = 1
            while new_filename.lower() in used_filenames or os.path.exists(os.path.join(dir_of_file, new_filename)):
                new_filename = f"{base_name}_{counter}.MP4"
                counter += 1

            used_filenames.add(new_filename.lower())
            new_file_path = os.path.join(dir_of_file, new_filename)
            os.rename(filepath, new_file_path)
            os.utime(new_file_path, (mod_time, mod_time))
            umbenannt += 1
            print(f"✅ File '{filename}' renamed to: {new_filename}")

    # Google Pixel PXL_ files
    elif lower_filename.endswith('.mp4') and filename.startswith('PXL_'):
        pxl_match = re.match(r"PXL_(\d{8})_(\d{6,})\.mp4", filename, re.IGNORECASE)
        if pxl_match:
            yyyymmdd, time_part = pxl_match.groups()
            try:
                year = int(yyyymmdd[0:4])
                month = int(yyyymmdd[4:6])
                day = int(yyyymmdd[6:8])
                hour = int(time_part[0:2])
                minute = int(time_part[2:4])
                second = int(time_part[4:6])
                dt = datetime(year, month, day, hour, minute, second)
                date_prefix = dt.strftime('%Y.%m.%d_%H.%M.%S')
            except Exception:
                date_prefix = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y.%m.%d_%H.%M.%S')

            base_name = f"{date_prefix}_Google-Pixel"
            new_filename = f"{base_name}.MP4"
            counter = 1
            while new_filename.lower() in used_filenames or os.path.exists(os.path.join(dir_of_file, new_filename)):
                new_filename = f"{base_name}_{counter}.MP4"
                counter += 1

            used_filenames.add(new_filename.lower())
            new_file_path = os.path.join(dir_of_file, new_filename)
            os.rename(filepath, new_file_path)
            os.utime(new_file_path, (mod_time, mod_time))
            umbenannt += 1
            print(f"✅ File '{filename}' renamed to: {new_filename}")

    # Images
    elif lower_filename.endswith(('.jpg', '.jpeg', '.png', '.heic', '.bmp')):
        base_ext = os.path.splitext(filename)[1]
        base_name = f"{date_prefix}_img"
        new_filename = f"{base_name}{base_ext}"
        new_file_path = os.path.join(dir_of_file, new_filename)

        if os.path.basename(filepath) != new_filename:
            if new_filename.lower() in used_filenames or os.path.exists(new_file_path):
                counter = 1
                while True:
                    candidate = f"{base_name}_{counter}{base_ext}"
                    candidate_path = os.path.join(dir_of_file, candidate)
                    if candidate.lower() not in used_filenames and not os.path.exists(candidate_path):
                        new_filename = candidate
                        new_file_path = candidate_path
                        break
                    counter += 1

            used_filenames.add(new_filename.lower())
            os.rename(filepath, new_file_path)
            os.utime(new_file_path, (mod_time, mod_time))
            umbenannt += 1
            print(f"🖼️ Image '{filename}' renamed to: {new_filename}")


# === DELETE DUPLICATES (at the end) ===
dupl_deleted = find_and_delete_duplicates(script_dir)

# === FINAL REPORT ===
print("\n📊 Summary:")
print(f"📁 Original files: {total_files}")
print(f"✏️ Renamed: {umbenannt}")
print(f"🗑️ Deleted during renaming (MP4): {gelöscht_mp4}")
print(f"🧹 Deleted by duplicate check: {dupl_deleted}")
print("\n🎉 Processing completed!")