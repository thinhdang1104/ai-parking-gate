"""Unit tests for YOLOv8 training entrypoints."""

from __future__ import annotations

from pathlib import Path

from src.training import train_chars, train_plates


def test_resolve_dataset_yaml_points_to_existing_files() -> None:
    plates_yaml = train_plates.resolve_dataset_yaml()
    chars_yaml = train_chars.resolve_dataset_yaml()

    assert plates_yaml.is_file()
    assert plates_yaml.parts[-3:] == ("datasets", "plates", "data.yaml")

    assert chars_yaml.is_file()
    assert chars_yaml.parts[-3:] == ("datasets", "chars", "data.yaml")


def test_build_train_kwargs_defaults() -> None:
    plates_kwargs = train_plates.build_train_kwargs(device="cpu")
    assert plates_kwargs == {
        "data": str(train_plates.resolve_dataset_yaml()),
        "imgsz": 640,
        "epochs": 50,
        "batch": 16,
        "device": "cpu",
        "workers": 2,
        "patience": 100,
        "seed": 0,
        "verbose": True,
    }

    chars_kwargs = train_chars.build_train_kwargs(device="cpu")
    assert chars_kwargs == {
        "data": str(train_chars.resolve_dataset_yaml()),
        "imgsz": 640,
        "epochs": 80,
        "batch": 8,
        "device": "cpu",
        "workers": 2,
        "patience": 20,
        "seed": 0,
        "verbose": True,
    }


def test_build_train_kwargs_allows_custom_data_yaml_and_device() -> None:
    custom_yaml = Path("custom/data.yaml")
    plates_kwargs = train_plates.build_train_kwargs(data_yaml=custom_yaml, device=0, verbose=False)
    chars_kwargs = train_chars.build_train_kwargs(data_yaml=custom_yaml, device=0, verbose=False)

    assert plates_kwargs["data"] == str(custom_yaml)
    assert plates_kwargs["device"] == 0
    assert plates_kwargs["verbose"] is False

    assert chars_kwargs["data"] == str(custom_yaml)
    assert chars_kwargs["device"] == 0
    assert chars_kwargs["verbose"] is False


def test_parse_args_overrides_cleanly() -> None:
    cli_args = ["--epochs", "5", "--batch", "4", "--device", "cpu", "--quiet"]

    plates_args = train_plates.parse_args(cli_args)
    assert plates_args.model == "yolov8n.pt"
    assert plates_args.data is None
    assert plates_args.epochs == 5
    assert plates_args.batch == 4
    assert plates_args.imgsz == 640
    assert plates_args.device == "cpu"
    assert plates_args.workers == 2
    assert plates_args.patience == 100
    assert plates_args.seed == 0
    assert plates_args.quiet is True

    chars_args = train_chars.parse_args(cli_args)
    assert chars_args.model == "yolov8n.pt"
    assert chars_args.data is None
    assert chars_args.epochs == 5
    assert chars_args.batch == 4
    assert chars_args.imgsz == 640
    assert chars_args.device == "cpu"
    assert chars_args.workers == 2
    assert chars_args.patience == 20
    assert chars_args.seed == 0
    assert chars_args.quiet is True
