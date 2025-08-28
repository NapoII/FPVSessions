import os
import subprocess

# 📂 Hauptordner – bitte anpassen!
input_folder = r"H:\FPV\FPVSessions\FPVSession_01.May.2025\FPVSession_01.May.2025_16.43.26-18.39.13"

# 📍 Pfad zur ffmpeg.exe – unbedingt korrekt setzen!
ffmpeg_path = r'C:\Users\napo\Downloads\ffmpeg-2025-03-31-git-35c091f4b7-full_build\ffmpeg-2025-03-31-git-35c091f4b7-full_build\bin\ffmpeg.exe'

# 🎥 Erlaubte Videoformate (außer mp4)
video_extensions = {".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm"}

# 🖼️ Bildformate zum Ignorieren
image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}

# 🎯 Qualitätseinstellung
CRF_VALUE = "18"


# 🔍 Durchsuche alle Unterordner
for root, dirs, files in os.walk(input_folder):
    for filename in files:
        ext = os.path.splitext(filename)[1].lower()

        # Ignoriere Bilder
        if ext in image_extensions:
            continue

        # Nur Videos verarbeiten, die nicht .mp4 sind
        if ext in video_extensions:
            input_path = os.path.join(root, filename)
            output_filename = os.path.splitext(filename)[0] + ".mp4"
            output_path = os.path.join(root, output_filename)

            # Änderungszeit sichern (mtime!)
            try:
                modified_timestamp = os.path.getmtime(input_path)
            except Exception as e:
                modified_timestamp = None
                print(f"⚠️  Konnte Änderungsdatum nicht lesen für {filename}: {e}")

            # Überspringen, wenn .mp4 bereits existiert
            if os.path.exists(output_path):
                print(f"⏭️  Übersprungen (bereits konvertiert): {output_filename}")
                continue

            print(f"🎬 Konvertiere: {input_path} → {output_path}")

            command = [
                ffmpeg_path,
                "-i", input_path,
                "-c:v", "libx264",
                "-crf", CRF_VALUE,
                "-preset", "fast",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                output_path
            ]

            try:
                subprocess.run(command, check=True)
                print(f"✅ Fertig: {output_filename}")

                # Zeitstempel (nur mtime) übernehmen
                if modified_timestamp:
                    os.utime(output_path, (modified_timestamp, modified_timestamp))
                    print(f"🕒 Änderungszeit übernommen: {output_filename}")

            except subprocess.CalledProcessError as e:
                print(f"❌ Fehler bei {filename}: {e}")
