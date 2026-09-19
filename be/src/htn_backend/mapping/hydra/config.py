"""Fixed Hydra settings shared by production and replay validation."""

from pathlib import Path

import yaml

LABELS = [
    "unknown",
    "chair",
    "couch",
    "dining table",
    "tv",
    "bed",
    "refrigerator",
    "oven",
    "sink",
    "toilet",
    "bottle",
    "cup",
    "laptop",
    "person",
    "cell phone",
]


class Loader(yaml.SafeLoader):
    """Support config_utilities' optional-field null tag."""


Loader.add_constructor("null", lambda loader, node: None)


def merge(target, updates):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = value
    return target


def configuration(hydra, upstream: Path):
    config = yaml.load(hydra.HydraPipeline.default_config(), Loader=Loader)
    merge(config, yaml.safe_load((upstream / "config/datasets/habitat.yaml").read_text()))
    config.update(
        total_semantic_labels=len(LABELS),
        dynamic_labels=[LABELS.index("person")],
        invalid_labels=[],
        object_labels=[i for i in range(1, len(LABELS)) if LABELS[i] != "person"],
        label_names=[{"label": i, "name": name} for i, name in enumerate(LABELS)],
        default_num_threads=2,
    )
    config["active_window"]["volumetric_map"].update(voxel_size=0.04, truncation_distance=0.12)
    config["active_window"]["full_update_separation_s"] = 0.4
    config["frontend"]["freespace_places"]["gvd"]["min_distance_m"] = 0.08
    # config_utilities serializes an unset optional as a custom null tag;
    # ordinary YAML null is not a valid LayerKey. Omission preserves its default.
    for layer in config["frontend"]["graph_updater"]["layer_updates"].values():
        if layer.get("target_layer") is None:
            layer.pop("target_layer", None)
    return config
