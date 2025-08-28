import cv2
import os
from PIL import Image

def generate_thumbnail(video_path, thumb_path):
    try:
        vidcap = cv2.VideoCapture(video_path)
        success, image = vidcap.read()
        if success:
            # Optional: Frame aus der Mitte nehmen
            total_frames = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
            vidcap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
            success, image = vidcap.read()
            if success:
                # Bild als JPEG speichern
                im = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                im.thumbnail((400, 225))
                im.save(thumb_path, "JPEG")
                return True
        return False
    except Exception as e:
        print(f"Fehler beim Generieren des Thumbnails: {e}")
        return False
