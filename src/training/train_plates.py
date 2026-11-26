"""YOLOv8 training entrypoint for the DATN2 license-plate detector."""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_dataset_yaml() -> Path:
    """Return the path to the license-plate dataset YAML configuration."""
    return REPO_ROOT / "datasets" / "plates" / "data.yaml"


def resolve_device(device: int | str | None = None) -> int | str:
    """Return the requested training device or auto-detect CUDA availability."""
    if device is not None:
        return device
    import torch

    return 0 if torch.cuda.is_available() else "cpu"


def build_train_kwargs(
    data_yaml: Path | None = None,
    device: int | str | None = None,
    epochs: int = 50,
    batch: int = 16,
    imgsz: int = 640,
    workers: int = 2,
    patience: int = 100,
    seed: int = 0,
    verbose: bool = True,
) -> dict[str, object]:
    """Build keyword arguments for ``YOLO.train`` with plate-model defaults."""
    resolved_data = data_yaml if data_yaml is not None else resolve_dataset_yaml()
    return {
        "data": str(resolved_data),
        "imgsz": imgsz,
        "epochs": epochs,
        "batch": batch,
        "device": resolve_device(device),
        "workers": workers,
        "patience": patience,
        "seed": seed,
        "verbose": verbose,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for license-plate model training."""
    parser = argparse.ArgumentParser(description="Train YOLOv8 license-plate detector.")
    parser.add_argument("--model", default="yolov8n.pt", help="Base YOLO model weights or config.")
    parser.add_argument("--data", default=None, help="Path to dataset data.yaml.")
    parser.add_argument("--epochs", type=int, default=50, help="Number of training epochs.")
    parser.add_argument("--batch", type=int, default=16, help="Training batch size.")
    parser.add_argument("--imgsz", type=int, default=640, help="Input image size.")
    parser.add_argument("--device", default=None, help="Target device (e.g. 0 or cpu).")
    parser.add_argument("--workers", type=int, default=2, help="Number of dataloader workers.")
    parser.add_argument("--patience", type=int, default=100, help="Early stopping patience.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed.")
    parser.add_argument("--quiet", action="store_true", help="Disable verbose Ultralytics output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run YOLOv8 training for the license-plate detection model."""
    args = parse_args(argv)
    kwargs = build_train_kwargs(
        data_yaml=Path(args.data) if args.data is not None else None,
        device=args.device,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        workers=args.workers,
        patience=args.patience,
        seed=args.seed,
        verbose=not args.quiet,
    )
    from ultralytics import YOLO

    model = YOLO(args.model)
    model.train(**kwargs)


if __name__ == "__main__":
    main()
