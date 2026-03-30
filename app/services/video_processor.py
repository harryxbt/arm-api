import logging
import os
import subprocess

import cv2

logger = logging.getLogger(__name__)

FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")

# Font name must match the font's internal name (what fc-list or the TTF reports)
CAPTION_FONTS = {
    "bangers": "Bangers",
    "anton": "Anton",
    "bebas": "Bebas Neue",
    "poppins": "Poppins",
    "impact": "Impact",
    "arial": "Arial",
}

DEFAULT_CAPTION_STYLE = {
    "font": "bangers",
    "font_size": 130,
    "words_per_chunk": 3,
    "position": "center",       # "top", "center", "bottom"
    "primary_color": "FFFFFF",   # white (RGB hex)
    "highlight_color": "00FFFF", # yellow (RGB hex)
    "outline_color": "000000",   # black (RGB hex)
    "outline_width": 4,
    "highlight": False,          # word-by-word highlight off by default
}


def _ass_color(hex_rgb: str) -> str:
    """Convert RGB hex to ASS color format (&H00BBGGRR)."""
    r = hex_rgb[0:2]
    g = hex_rgb[2:4]
    b = hex_rgb[4:6]
    return f"&H00{b}{g}{r}"


def _seconds_to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _get_vertical_margin(position: str) -> int:
    """Get MarginV for caption position.
    With Alignment 5 (center-center), MarginV shifts down from center (960px).
    On 1920px video, source is top 960px. We want captions in that top half.
    Negative MarginV not supported, so we use positive values to shift within top half."""
    if position == "top":
        return 600   # shifted up from center into top area
    elif position == "center":
        return 480   # center of source video (960/2 = 480 from center of full frame)
    else:  # bottom
        return 200   # just above the split line


def generate_ass_subtitles(words: list[dict], output_path: str, style: dict | None = None) -> None:
    """Generate ASS subtitle file with centered captions."""
    cfg = {**DEFAULT_CAPTION_STYLE, **(style or {})}

    font_name = CAPTION_FONTS.get(cfg["font"], cfg["font"])
    font_size = cfg["font_size"]
    primary = _ass_color(cfg["primary_color"])
    highlight = _ass_color(cfg["highlight_color"])
    outline = _ass_color(cfg["outline_color"])
    outline_w = cfg["outline_width"]
    margin_v = _get_vertical_margin(cfg["position"])
    words_per_chunk = cfg["words_per_chunk"]
    do_highlight = cfg["highlight"]

    # Alignment 5 = center-center. MarginV shifts from center of screen.
    header = f"""[Script Info]
Title: Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},&H000000FF,{outline},&H80000000,0,0,0,0,100,100,0,0,1,{outline_w},0,5,10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    i = 0
    while i < len(words):
        chunk = words[i:i + words_per_chunk]
        if not chunk:
            break

        chunk_start = chunk[0]["start"]
        chunk_end = chunk[-1]["end"]
        start_ts = _seconds_to_ass_time(chunk_start)
        end_ts = _seconds_to_ass_time(chunk_end)

        if do_highlight and len(chunk) > 1:
            text_parts = []
            for j, w in enumerate(chunk):
                word_text = w["word"].upper()
                duration_cs = int((w["end"] - w["start"]) * 100)
                text_parts.append(
                    f"{{\\kf{duration_cs}\\1c{highlight}}}{word_text}{{\\1c{primary}}}"
                )
            text = " ".join(text_parts)
        else:
            text = " ".join(w["word"].upper() for w in chunk)

        events.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}")
        i += len(chunk)

    with open(output_path, "w") as f:
        f.write(header)
        f.write("\n".join(events))


def _get_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    import json
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
        capture_output=True, text=True, timeout=10,
    )
    try:
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except (json.JSONDecodeError, ValueError):
        return 0


def _detect_face_y_ratio(video_path: str, num_samples: int = 5) -> float | None:
    """Sample a few frames and return the average face vertical center as a ratio (0=top, 1=bottom).
    Returns None if no face detected. Uses OpenCV Haar cascades (fast, no mediapipe needed)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 1:
        cap.release()
        return None

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    y_ratios = []

    for i in range(num_samples):
        frame_pos = int(total_frames * (i + 1) / (num_samples + 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
        ret, frame = cap.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        if len(faces) > 0:
            # Take the largest face
            largest = max(faces, key=lambda f: f[2] * f[3])
            x, y, w, h = largest
            face_center_y = (y + h / 2) / frame.shape[0]
            y_ratios.append(face_center_y)

    cap.release()

    if not y_ratios:
        logger.info("No face detected in %s, using default crop", os.path.basename(video_path))
        return None

    avg = sum(y_ratios) / len(y_ratios)
    logger.info("Face detected at %.0f%% from top in %s (%d/%d samples)",
                avg * 100, os.path.basename(video_path), len(y_ratios), num_samples)
    return avg


def composite_splitscreen(
    source_path: str,
    gameplay_path: str,
    ass_path: str | None,
    output_path: str,
) -> None:
    """Composite splitscreen video with optional captions.
    Picks a random start point in the gameplay clip for variation."""
    import random

    # Get durations to pick a random gameplay offset
    source_duration = _get_duration(source_path)
    gameplay_duration = _get_duration(gameplay_path)

    # Pick random offset — ensure enough gameplay left to cover the source
    gameplay_ss = 0
    if gameplay_duration > source_duration:
        max_offset = gameplay_duration - source_duration
        gameplay_ss = random.uniform(0, max_offset)

    # Detect face position to crop intelligently
    face_y = _detect_face_y_ratio(source_path)

    # We need to know the scaled height to compute the crop y offset.
    # scale with force_original_aspect_ratio=increase scales to fill 1080x960,
    # so the scaled height = max(960, src_height * 1080 / src_width).
    import json as _json
    _probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "v:0", source_path],
        capture_output=True, text=True, timeout=10,
    )
    try:
        _stream = _json.loads(_probe.stdout)["streams"][0]
        src_w, src_h = int(_stream["width"]), int(_stream["height"])
    except (KeyError, IndexError, ValueError):
        src_w, src_h = 1920, 1080

    scaled_h = max(960, int(src_h * 1080 / src_w)) if src_w > 0 else 960

    if face_y is not None and scaled_h > 960:
        # face_y is 0-1 ratio. Face is at face_y * scaled_h pixels.
        # Center the 960px crop on the face, clamped to valid range.
        face_px = face_y * scaled_h
        crop_y = int(max(0, min(scaled_h - 960, face_px - 480)))
    else:
        crop_y = 0

    # Use overlay instead of vstack to eliminate any gap between halves
    # Source on top (scaled to fill 1080x960), gameplay directly below
    filter_parts = [
        f"[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960:(iw-1080)/2:{crop_y}[top]",
        "[1:v]scale=1080:1040:force_original_aspect_ratio=increase,crop=1080:1040,setpts=PTS-STARTPTS[bot]",
        "color=black:1080x1920:d=999[base]",
        "[base][top]overlay=0:-40[tmp]",
        "[tmp][bot]overlay=0:880[v]",
    ]

    if ass_path and os.path.exists(ass_path):
        escaped_ass = ass_path.replace("\\", "\\\\").replace(":", "\\:")
        fonts_dir = os.path.abspath(FONTS_DIR)
        escaped_fonts = fonts_dir.replace("\\", "\\\\").replace(":", "\\:")
        filter_parts.append(
            f"[v]ass={escaped_ass}:fontsdir={escaped_fonts}[out]"
        )
        map_video = "[out]"
    else:
        map_video = "[v]"

    filter_complex = ";\n".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-ss", str(gameplay_ss),
        "-stream_loop", "-1", "-i", gameplay_path,
        "-filter_complex", filter_complex,
        "-map", map_video,
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-500:]}")
