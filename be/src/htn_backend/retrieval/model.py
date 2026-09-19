"""Pinned SigLIP 2 image/text encoder; CUDA work stays on the server."""

import numpy as np

MODEL = "google/siglip2-base-patch16-224"
REVISION = "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2"
MODEL_KEY = f"{MODEL}@{REVISION}"


class Encoder:
    def __init__(self):
        import torch
        from transformers import AutoImageProcessor, AutoModel, AutoTokenizer

        torch.set_num_threads(2)
        self.torch = torch
        self.image_processor = AutoImageProcessor.from_pretrained(
            MODEL, revision=REVISION, use_fast=False
        )
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
        self.model = (
            AutoModel.from_pretrained(MODEL, revision=REVISION, torch_dtype=torch.float16)
            .cuda()
            .eval()
        )

    def encode(self, *, images=None, text=None):
        if images is not None:
            inputs = self.image_processor(images=images, return_tensors="pt").to("cuda")
            inputs["pixel_values"] = inputs["pixel_values"].half()
            method = self.model.get_image_features
        else:
            inputs = self.tokenizer(
                text=text,
                padding="max_length",
                max_length=64,
                truncation=True,
                return_tensors="pt",
            ).to("cuda")
            method = self.model.get_text_features
        with self.torch.inference_mode():
            result = method(**inputs)
            if not isinstance(result, self.torch.Tensor):
                result = result.pooler_output
            result = result.float()
            result = result / result.norm(dim=-1, keepdim=True).clamp(min=1e-8)
        values = result.cpu().numpy().astype(np.float32)
        if values.ndim != 2 or not np.isfinite(values).all():
            raise ValueError("Invalid image/text embeddings")
        return values
