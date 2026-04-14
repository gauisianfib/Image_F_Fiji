# service/nd2_image_service.py
import numpy as np
from PIL import Image
from utils.image_utils import apply_min_max_12bit, create_cmy_simple_composite


class ND2ImageService:
    def __init__(self, config):
        self.config = config

    def get_current_channels(self, data, sizes, current_z, current_t, axis_order):
        shape = data.shape
        idx = [slice(None)] * len(shape)

        z_idx = axis_order.index('Z') if 'Z' in sizes else None
        t_idx = axis_order.index('T') if 'T' in sizes else None
        c_idx = axis_order.index('C') if 'C' in sizes else None

        if z_idx is not None and sizes.get('Z', 1) > 1:
            idx[z_idx] = current_z
        if t_idx is not None and sizes.get('T', 1) > 1:
            idx[t_idx] = current_t

        channels = []
        num_c = sizes.get('C', 1)

        for c in range(min(3, num_c)):
            idx_c = idx[:]
            if c_idx is not None:
                idx_c[c_idx] = c
            ch = data[tuple(idx_c)]
            channels.append(ch)

        if channels:
            h, w = channels[0].shape
        else:
            h, w = 512, 512

        while len(channels) < 3:
            channels.append(np.zeros((h, w), dtype=np.uint16))

        return channels

    def create_composite_image(self, channels, channel_enabled, channel_params, display_mode):
        adjusted = []
        for i in range(3):
            if channel_enabled[i]:
                adj = apply_min_max_12bit(channels[i], channel_params[i]["min"], channel_params[i]["max"])
                adjusted.append(adj)
            else:
                h, w = channels[0].shape if channels else (512, 512)
                adjusted.append(np.zeros((h, w), dtype=np.uint8))

        if display_mode == "CMY":
            rgb = create_cmy_simple_composite(adjusted)
        elif display_mode == "RGB":
            rgb = np.stack([adjusted[0], adjusted[1], adjusted[2]], axis=2)
        elif display_mode == "BGR":
            rgb = np.stack([adjusted[2], adjusted[1], adjusted[0]], axis=2)
        else:
            rgb = np.zeros((512, 512, 3), dtype=np.uint8)

        return rgb

    def save_composite(self, channels, channel_enabled, channel_params, display_mode):
        rgb = self.create_composite_image(channels, channel_enabled, channel_params, display_mode)
        return Image.fromarray(rgb)