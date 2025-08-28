import os
import subprocess

def generate_thumbnail(video_path: str, thumb_path: str) -> bool:
    """Generate thumbnail from video using ffmpeg. Returns True if successful."""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

        # Use ffmpeg to generate thumbnail at 5 seconds into the video
        cmd = [
            'ffmpeg', '-y',  # overwrite output file
            '-i', video_path,
            '-ss', '5',      # seek to 5 seconds
            '-vframes', '1', # extract 1 frame
            '-vf', 'scale=320:240:force_original_aspect_ratio=decrease',  # resize
            thumb_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0 and os.path.exists(thumb_path)
    except Exception as e:
        print(f"❌ Thumbnail generation failed for {video_path}: {e}")
        return False
