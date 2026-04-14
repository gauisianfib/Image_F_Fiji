# utils/image_utils.py
import numpy as np


def apply_min_max_12bit(ch, min_val, max_val):
    ch = ch.astype(np.float32)
    ch = np.clip(ch, min_val, max_val)
    ch = (ch - min_val) / (max_val - min_val + 1e-8) * 255.0
    return np.clip(ch, 0, 255).astype(np.uint8)


def create_cmy_simple_composite(channels_list):
    if not channels_list or len(channels_list) == 0:
        return np.zeros((512, 512, 3), dtype=np.uint8)

    h, w = channels_list[0].shape[:2]

    ch0 = channels_list[0] if len(channels_list) > 0 else np.zeros((h, w), dtype=np.uint8)
    ch1 = channels_list[1] if len(channels_list) > 1 else np.zeros((h, w), dtype=np.uint8)
    ch2 = channels_list[2] if len(channels_list) > 2 else np.zeros((h, w), dtype=np.uint8)

    rgb = np.zeros((h, w, 3), dtype=np.uint8)

    rgb[..., 1] = np.clip(ch0, 0, 255)
    rgb[..., 2] = np.clip(ch0, 0, 255)
    rgb[..., 0] = np.clip(rgb[..., 0] + ch1, 0, 255)
    rgb[..., 2] = np.clip(rgb[..., 2] + ch1, 0, 255)
    rgb[..., 0] = np.clip(rgb[..., 0] + ch2, 0, 255)
    rgb[..., 1] = np.clip(rgb[..., 1] + ch2, 0, 255)

    return rgb