"""One production inference profile on the private GPU endpoint."""

import os

import torch
from PIL import Image

from ..perception.rfdetr import RFDetrSegmenter
from .features import Features
from .service import create_app


def application():
    torch.set_num_threads(4)
    model = RFDetrSegmenter()
    with torch.inference_mode():
        for count in (1, 2, 4):
            model.model.predict([Image.new("RGB", (960, 720))] * count, threshold=0.35)
    torch.cuda.synchronize()
    return create_app(model, os.environ["HTN_GPU_TOKEN"], Features())
