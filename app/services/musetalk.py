# app/services/musetalk.py
"""Local MuseTalk lip-sync inference service.

Replaces the Sync Labs API with local GPU inference via MuseTalk v1.5.
Models are loaded once on first call and reused across requests.

Requires MuseTalk to be installed (clone repo, install deps, download weights).
Set MUSETALK_DIR to the root of the MuseTalk repo.
"""
import logging
import os
import subprocess
import sys
import tempfile
import uuid

from app.config import settings

logger = logging.getLogger(__name__)

_models_loaded = False
_inference_fn = None


def _ensure_musetalk_on_path():
    """Add MuseTalk repo to sys.path if not already there."""
    musetalk_dir = settings.musetalk_dir
    if not musetalk_dir:
        raise RuntimeError(
            "MUSETALK_DIR not set. Point it to the root of your MuseTalk clone."
        )
    if not os.path.isdir(musetalk_dir):
        raise RuntimeError(f"MUSETALK_DIR does not exist: {musetalk_dir}")
    if musetalk_dir not in sys.path:
        sys.path.insert(0, musetalk_dir)


def _load_models():
    """Lazy-load MuseTalk models on first inference call."""
    global _models_loaded, _inference_fn

    if _models_loaded:
        return

    _ensure_musetalk_on_path()

    logger.info("Loading MuseTalk models (first call, this takes a moment)...")

    import torch
    from musetalk.utils.utils import load_all_model
    from musetalk.utils.preprocessing import get_landmark_and_bbox
    from musetalk.utils.blending import get_image
    from musetalk.utils.utils import get_file_type, get_video_fps, datagen

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        logger.warning("No CUDA GPU detected — MuseTalk will be extremely slow on CPU")

    # Load all model components (VAE, UNet, PE, face parser, whisper)
    model_dir = settings.musetalk_model_dir
    unet_path = os.path.join(model_dir, "musetalkV15", "unet.pth")
    unet_config = os.path.join(model_dir, "musetalkV15", "musetalk.json")

    if not os.path.isfile(unet_path):
        raise RuntimeError(f"MuseTalk UNet weights not found at {unet_path}")

    audio_processor, vae, unet, pe = load_all_model(
        unet_model_path=unet_path,
        unet_config=unet_config,
        device=device,
    )

    logger.info("MuseTalk models loaded on %s", device)

    def run_inference(video_path: str, audio_path: str, output_path: str):
        """Run MuseTalk lipsync inference on a single video+audio pair."""
        import cv2
        import numpy as np
        from musetalk.utils.preprocessing import get_landmark_and_bbox, coord_placeholder
        from musetalk.utils.blending import get_image_prepare_material, get_image
        from musetalk.utils.utils import get_video_fps, datagen

        fps = get_video_fps(video_path)

        # Extract frames
        tmp_frames = tempfile.mkdtemp(prefix="musetalk_frames_")
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", video_path,
                "-qscale:v", "2",
                os.path.join(tmp_frames, "%08d.png"),
            ],
            check=True,
            capture_output=True,
        )

        frame_files = sorted(
            [os.path.join(tmp_frames, f) for f in os.listdir(tmp_frames) if f.endswith(".png")]
        )
        if not frame_files:
            raise RuntimeError("Failed to extract frames from video")

        # Get face landmarks and bounding boxes
        coord_list, frame_list = get_landmark_and_bbox(frame_files, upperbondrange=0)
        # Replace None coords with placeholders
        for i, coord in enumerate(coord_list):
            if coord is None:
                coord_list[i] = coord_placeholder

        # Process audio features
        whisper_chunks = audio_processor.get_whisper_chunks(
            audio_path, device=device
        )

        # Run inference
        tmp_output_frames = tempfile.mkdtemp(prefix="musetalk_out_")
        gen = datagen(
            whisper_chunks,
            vae,
            frame_list,
            coord_list,
            batch_size=8,
            device=device,
        )

        frame_idx = 0
        for whisper_batch, latent_batch, coord_batch, original_frames in gen:
            with torch.no_grad():
                pred = unet.model(
                    latent_batch,
                    timesteps=torch.zeros(latent_batch.shape[0], device=device).long(),
                    encoder_hidden_states=pe(whisper_batch),
                ).sample

            pred_decoded = vae.decode(pred / vae.config.scaling_factor).sample
            pred_decoded = (pred_decoded.clamp(-1, 1) + 1) / 2 * 255
            pred_decoded = pred_decoded.permute(0, 2, 3, 1).cpu().numpy().astype(np.uint8)

            for j in range(pred_decoded.shape[0]):
                result_frame = get_image(
                    pred_decoded[j],
                    coord_batch[j],
                    original_frames[j],
                )
                out_path = os.path.join(tmp_output_frames, f"{frame_idx:08d}.png")
                cv2.imwrite(out_path, result_frame)
                frame_idx += 1

        # Combine frames + audio into final video
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-r", str(fps),
                "-i", os.path.join(tmp_output_frames, "%08d.png"),
                "-i", audio_path,
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                "-pix_fmt", "yuv420p",
                output_path,
            ],
            check=True,
            capture_output=True,
        )

        # Cleanup temp dirs
        import shutil
        shutil.rmtree(tmp_frames, ignore_errors=True)
        shutil.rmtree(tmp_output_frames, ignore_errors=True)

        file_size = os.path.getsize(output_path) / (1024 * 1024)
        logger.info("MuseTalk output saved: %s (%.1f MB, %d frames)", output_path, file_size, frame_idx)

    _inference_fn = run_inference
    _models_loaded = True


def run_lipsync(video_path: str, audio_path: str, output_path: str) -> str:
    """Run local MuseTalk lip-sync. Returns the output file path.

    Args:
        video_path: Path to the source video file.
        audio_path: Path to the dubbed audio file.
        output_path: Path where the lip-synced video will be saved.

    Returns:
        The output_path on success.
    """
    _load_models()

    logger.info(
        "Running MuseTalk lipsync: video=%s audio=%s -> %s",
        os.path.basename(video_path),
        os.path.basename(audio_path),
        os.path.basename(output_path),
    )

    _inference_fn(video_path, audio_path, output_path)

    if not os.path.isfile(output_path):
        raise RuntimeError(f"MuseTalk inference completed but output file not found: {output_path}")

    return output_path
