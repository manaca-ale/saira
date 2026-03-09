from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
from ultralytics import YOLO

WASTE_TYPE_MAP = {
    "entulho": "Entulho",
    "lixo domiciliar": "Lixo domiciliar",
    "restos de madeira": "Entulho",
    "terra": "Entulho",
}

OFFENDER_TYPE_MAP = {
    "person": "Pessoa",
    "car": "Carro",
    "truck": "Carro",
    "bus": "Carro",
    "motorcycle": "Moto",
    "bicycle": "Outro",
}

P1_COLOR = (0, 0, 255)      # Red (BGR)
P2_COLOR = (255, 140, 0)    # Blue-ish (BGR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SAIRA current detection models over a folder of images.")
    parser.add_argument("--input-dir", required=True, help="Input directory containing camera subfolders (1,2,3).")
    parser.add_argument("--output-dir", required=True, help="Directory where labeled images + summary files are saved.")
    parser.add_argument("--p1-model", required=True, help="Path to P1 model (garbage).")
    parser.add_argument("--p2-model", required=True, help="Path to P2 model (offenders).")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold for both models.")
    return parser.parse_args()


def draw_box(img: Any, bbox: list[float], label: str, color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = [int(round(v)) for v in bbox]
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    cv2.putText(
        img,
        label,
        (x1, max(16, y1 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        color,
        2,
        cv2.LINE_AA,
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def collect_images(input_dir: Path) -> list[tuple[str, Path]]:
    rows: list[tuple[str, Path]] = []
    for camera_dir in sorted([p for p in input_dir.iterdir() if p.is_dir()], key=lambda p: p.name):
        for img in sorted(camera_dir.glob("*.jpg"), key=lambda p: p.name):
            rows.append((camera_dir.name, img))
    return rows


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    labeled_root = output_dir / "labeled"

    if not input_dir.exists():
        raise FileNotFoundError(f"Input dir not found: {input_dir}")

    ensure_dir(output_dir)
    ensure_dir(labeled_root)

    p1 = YOLO(str(Path(args.p1_model).resolve()))
    p2 = YOLO(str(Path(args.p2_model).resolve()))

    rows = collect_images(input_dir)
    if not rows:
        raise RuntimeError(f"No JPG files found under: {input_dir}")

    per_camera: dict[str, dict[str, Any]] = {}
    image_results: list[dict[str, Any]] = []
    global_p1_classes = Counter()
    global_p2_classes = Counter()
    global_waste_types = Counter()
    global_offender_types = Counter()
    failed_images: list[str] = []

    for camera, img_path in rows:
        if camera not in per_camera:
            per_camera[camera] = {
                "images_total": 0,
                "images_with_garbage": 0,
                "images_with_offender": 0,
                "garbage_detections_total": 0,
                "offender_detections_total": 0,
                "garbage_classes": Counter(),
                "offender_classes": Counter(),
                "waste_types": Counter(),
                "offender_types": Counter(),
            }

        per_camera[camera]["images_total"] += 1
        cam_out = labeled_root / camera
        ensure_dir(cam_out)
        out_path = cam_out / img_path.name

        image = cv2.imread(str(img_path))
        if image is None:
            failed_images.append(str(img_path))
            continue

        try:
            # Use decoded array to avoid re-reading possibly unstable JPG files by path.
            p1_result = p1(image, verbose=False, conf=args.conf)[0]
            p2_result = p2(image, verbose=False, conf=args.conf)[0]
        except Exception:
            failed_images.append(str(img_path))
            continue

        p1_dets: list[dict[str, Any]] = []
        for box in p1_result.boxes:
            cls_idx = int(box.cls[0])
            class_name = str(p1.names[cls_idx])
            conf = float(box.conf[0])
            bbox = box.xyxy[0].tolist()
            waste_type = WASTE_TYPE_MAP.get(class_name.lower(), "Entulho")
            p1_dets.append(
                {
                    "class_name": class_name,
                    "confidence": round(conf, 4),
                    "bbox": [round(v, 2) for v in bbox],
                    "waste_type": waste_type,
                }
            )
            draw_box(image, bbox, f"P1 {class_name} {conf:.2f}", P1_COLOR)
            global_p1_classes[class_name] += 1
            global_waste_types[waste_type] += 1
            per_camera[camera]["garbage_classes"][class_name] += 1
            per_camera[camera]["waste_types"][waste_type] += 1

        p2_dets: list[dict[str, Any]] = []
        for box in p2_result.boxes:
            cls_idx = int(box.cls[0])
            class_name = str(p2.names[cls_idx])
            conf = float(box.conf[0])
            bbox = box.xyxy[0].tolist()
            offender_type = OFFENDER_TYPE_MAP.get(class_name.lower())
            if not offender_type:
                continue
            p2_dets.append(
                {
                    "class_name": class_name,
                    "confidence": round(conf, 4),
                    "bbox": [round(v, 2) for v in bbox],
                    "offender_type": offender_type,
                }
            )
            draw_box(image, bbox, f"P2 {class_name} {conf:.2f}", P2_COLOR)
            global_p2_classes[class_name] += 1
            global_offender_types[offender_type] += 1
            per_camera[camera]["offender_classes"][class_name] += 1
            per_camera[camera]["offender_types"][offender_type] += 1

        if p1_dets:
            per_camera[camera]["images_with_garbage"] += 1
        if p2_dets:
            per_camera[camera]["images_with_offender"] += 1
        per_camera[camera]["garbage_detections_total"] += len(p1_dets)
        per_camera[camera]["offender_detections_total"] += len(p2_dets)

        cv2.imwrite(str(out_path), image)

        image_results.append(
            {
                "camera": camera,
                "file_name": img_path.name,
                "input_path": str(img_path),
                "labeled_path": str(out_path),
                "garbage_count": len(p1_dets),
                "offender_count": len(p2_dets),
                "garbage_detections": p1_dets,
                "offender_detections": p2_dets,
            }
        )

    totals = {
        "images_total": len(rows),
        "images_processed": len(rows) - len(failed_images),
        "images_failed": len(failed_images),
        "images_with_garbage": sum(v["images_with_garbage"] for v in per_camera.values()),
        "images_with_offender": sum(v["images_with_offender"] for v in per_camera.values()),
        "garbage_detections_total": sum(v["garbage_detections_total"] for v in per_camera.values()),
        "offender_detections_total": sum(v["offender_detections_total"] for v in per_camera.values()),
    }

    normalized_per_camera = {}
    for camera, stats in per_camera.items():
        normalized_per_camera[camera] = {
            "images_total": stats["images_total"],
            "images_with_garbage": stats["images_with_garbage"],
            "images_with_offender": stats["images_with_offender"],
            "garbage_detections_total": stats["garbage_detections_total"],
            "offender_detections_total": stats["offender_detections_total"],
            "garbage_classes": dict(stats["garbage_classes"]),
            "offender_classes": dict(stats["offender_classes"]),
            "waste_types": dict(stats["waste_types"]),
            "offender_types": dict(stats["offender_types"]),
        }

    summary = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "models": {
            "p1": str(Path(args.p1_model).resolve()),
            "p2": str(Path(args.p2_model).resolve()),
            "conf_threshold": args.conf,
        },
        "totals": totals,
        "per_camera": normalized_per_camera,
        "global_classes": {
            "garbage_classes": dict(global_p1_classes),
            "offender_classes": dict(global_p2_classes),
            "waste_types": dict(global_waste_types),
            "offender_types": dict(global_offender_types),
        },
        "failed_images": failed_images,
        "images": image_results,
    }

    summary_json = output_dir / "summary.json"
    summary_md = output_dir / "summary.md"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Resumo de Deteccoes",
        "",
        f"- Run UTC: `{summary['run_at_utc']}`",
        f"- Input: `{summary['input_dir']}`",
        f"- Output: `{summary['output_dir']}`",
        f"- Modelo P1: `{summary['models']['p1']}`",
        f"- Modelo P2: `{summary['models']['p2']}`",
        f"- Threshold: `{summary['models']['conf_threshold']}`",
        "",
        "## Totais",
        f"- Imagens totais: **{totals['images_total']}**",
        f"- Imagens processadas: **{totals['images_processed']}**",
        f"- Imagens com falha: **{totals['images_failed']}**",
        f"- Imagens com deteccao de lixo (P1): **{totals['images_with_garbage']}**",
        f"- Imagens com deteccao de infrator (P2): **{totals['images_with_offender']}**",
        f"- Deteccoes totais P1: **{totals['garbage_detections_total']}**",
        f"- Deteccoes totais P2: **{totals['offender_detections_total']}**",
        "",
        "## Por Camera",
    ]

    for cam in sorted(normalized_per_camera.keys(), key=lambda x: str(x)):
        c = normalized_per_camera[cam]
        lines.extend(
            [
                f"### Camera {cam}",
                f"- Imagens: **{c['images_total']}**",
                f"- Imagens com P1: **{c['images_with_garbage']}**",
                f"- Imagens com P2: **{c['images_with_offender']}**",
                f"- Deteccoes P1: **{c['garbage_detections_total']}**",
                f"- Deteccoes P2: **{c['offender_detections_total']}**",
                f"- Classes P1: `{json.dumps(c['garbage_classes'], ensure_ascii=False)}`",
                f"- Classes P2: `{json.dumps(c['offender_classes'], ensure_ascii=False)}`",
                f"- Tipos de residuo: `{json.dumps(c['waste_types'], ensure_ascii=False)}`",
                f"- Tipos de infrator: `{json.dumps(c['offender_types'], ensure_ascii=False)}`",
                "",
            ]
        )

    summary_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"Processed images: {totals['images_processed']}/{totals['images_total']}")
    print(f"Labeled images folder: {labeled_root}")
    print(f"Summary JSON: {summary_json}")
    print(f"Summary MD: {summary_md}")


if __name__ == "__main__":
    main()
