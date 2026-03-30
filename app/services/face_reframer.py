import json
import os
import subprocess

import cv2
import mediapipe as mp


def get_video_dimensions(video_path: str) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-select_streams", "v:0", video_path,
        ],
        capture_output=True, text=True, timeout=10,
    )
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"])


def is_landscape(width: int, height: int) -> bool:
    return width > height


def smooth_positions(positions: list[float], window: int = 5) -> list[float]:
    if len(positions) <= 1:
        return positions
    smoothed = []
    for i in range(len(positions)):
        start = max(0, i - window // 2)
        end = min(len(positions), i + window // 2 + 1)
        avg = sum(positions[start:end]) / (end - start)
        smoothed.append(avg)
    return smoothed


def _detect_face_positions(video_path: str, sample_interval: float = 0.5) -> list[dict]:
    face_detection = mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    )

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = int(fps * sample_interval) if fps > 0 else 15
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    positions = []
    frame_idx = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            time_sec = frame_idx / fps if fps > 0 else 0
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_detection.process(rgb_frame)

            if results.detections:
                detection = results.detections[0]
                bbox = detection.location_data.relative_bounding_box
                center_x = int((bbox.xmin + bbox.width / 2) * width)
                center_y = int((bbox.ymin + bbox.height / 2) * height)
                positions.append({"time": time_sec, "x": center_x, "y": center_y})

        frame_idx += 1

    cap.release()
    face_detection.close()
    return positions


def _compute_crop_positions(
    face_positions: list[dict],
    src_width: int,
    src_height: int,
    target_width: int = 1080,
    target_height: int = 1920,
) -> list[float]:
    crop_h = src_height
    crop_w = int(crop_h * target_width / target_height)
    crop_w = min(crop_w, src_width)

    if not face_positions:
        x_offset = (src_width - crop_w) // 2
        return [float(x_offset)]

    raw_offsets = []
    for pos in face_positions:
        x = pos["x"] - crop_w // 2
        x = max(0, min(x, src_width - crop_w))
        raw_offsets.append(float(x))

    return smooth_positions(raw_offsets, window=5)


def reframe_to_vertical(input_path: str, output_path: str) -> bool:
    width, height = get_video_dimensions(input_path)

    if not is_landscape(width, height):
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ],
            capture_output=True, timeout=300,
        )
        return False

    face_positions = _detect_face_positions(input_path)

    crop_h = height
    crop_w = int(crop_h * 1080 / 1920)
    crop_w = min(crop_w, width)

    offsets = _compute_crop_positions(face_positions, width, height)

    avg_x = int(sum(offsets) / len(offsets))
    avg_x = max(0, min(avg_x, width - crop_w))
    crop_filter = f"crop={crop_w}:{crop_h}:{avg_x}:0,scale=1080:1920"

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", crop_filter,
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ],
        capture_output=True, timeout=300,
    )

    if not os.path.exists(output_path):
        raise RuntimeError(f"FFmpeg reframe failed — output not created: {output_path}")

    return True
