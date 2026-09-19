"""RF-DETR medium segmentation on the calibrated native depth grid."""

from io import BytesIO

import numpy as np
from PIL import Image

from ..capture.frame import Frame
from .instances import Detection
from .orientation import upright_quarter_turns


class RFDetrSegmenter:
    def __init__(self):
        import rfdetr
        import torch
        from rfdetr.assets.coco_classes import COCO_CLASSES

        self.model = rfdetr.RFDETRSegMedium(device="cuda")
        if self.model.model_config.num_classes != 90:
            raise ValueError("Adapter requires the stock COCO label mapping")
        self.class_names = COCO_CLASSES
        self.threshold = 0.35
        self.model.optimize_for_inference(compile=False, dtype=torch.float16)

    def prepare(self, frame: Frame):
        """Decode and orient on CPU before entering the GPU batch queue."""
        with Image.open(BytesIO(frame.rgb_jpeg)) as source:
            if source.size != (frame.header.rgb_width, frame.header.rgb_height):
                raise ValueError("JPEG dimensions disagree with frame metadata")
            source.load()
            image = source.convert("RGB")
        turns = upright_quarter_turns(frame.header)
        if turns:
            image = image.transpose(
                {
                    1: Image.Transpose.ROTATE_90,
                    2: Image.Transpose.ROTATE_180,
                    3: Image.Transpose.ROTATE_270,
                }[turns]
            )
        image.thumbnail((960, 960), Image.Resampling.BILINEAR)
        return frame, image, turns

    def __call__(self, frame: Frame) -> list[Detection]:
        if not frame.rgb_jpeg:
            return []
        return self.batch([self.prepare(frame)])[0]

    def batch(self, prepared) -> list[list[Detection]]:
        predictions = self.model.predict([item[1] for item in prepared], threshold=self.threshold)
        return [
            self.finish(item, prediction)
            for item, prediction in zip(prepared, predictions, strict=True)
        ]

    def finish(self, prepared, predictions) -> list[Detection]:
        frame, image, turns = prepared
        if predictions.mask is None:
            raise ValueError("segmentation model returned no mask array")
        rows = [
            (int(c), float(s), m)
            for c, s, m in zip(
                predictions.class_id, predictions.confidence, predictions.mask, strict=True
            )
        ]
        result = []
        for class_id, score, mask in rows:
            native = np.rot90(mask, -turns).copy()
            target = (frame.header.depth_width, frame.header.depth_height)
            native = np.asarray(Image.fromarray(native).resize(target, Image.Resampling.NEAREST))
            label = str(self.class_names[class_id])
            duplicate = False
            for old in result:
                if old.label != label:
                    continue
                intersection = np.count_nonzero(native & old.mask)
                union = np.count_nonzero(native | old.mask)
                if union and intersection / union > 0.45:
                    duplicate = True
                    break
            if not duplicate:
                result.append(Detection(label, score, native))
        return result
