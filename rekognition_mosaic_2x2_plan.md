# SAIRA - AWS Rekognition 2x2 Mosaic Technical Plan

## Component Architecture
Current ingestion and processing path:
1. Edge devices upload to Flask receiver at `/upload`, which stores images under `UPLOAD_ROOT/device_id/YYYY/MM/DD/timestamp.jpg`.
2. Worker scans pending JPGs per device using `rglob("*.jpg")`.
3. Worker resolves camera by `device_id` from DB.
4. Worker calls inference and persists detections/offenders.
5. Rekognition is currently called per-image via `detect_labels`.

Target architecture for 2x2 tiling:
`Edge -> Flask Upload Storage -> Grouping Queue (worker-side) -> Mosaic Generator -> Single Rekognition API call -> Reverse Mapper -> Per-image detection fan-out -> DB/notifications/annotated image`

Recommended placement:
1. Keep grouping logic in worker, not in Flask upload endpoint.
2. Keep Flask endpoint lightweight and stateless for ingestion throughput.
3. Add a worker-side batching stage before inference for `AI_MODEL_PROVIDER=rekognition`.
4. Keep persistence unchanged (one detection record per original source image/camera), only reduce API call count.

## Grouping Mechanism Options
Option A (count-based only):
1. Process strictly when 4 pending images exist.
2. Pros: max cost reduction.
3. Cons: can stall under low traffic.

Option B (time-based only):
1. Flush based on oldest image age window.
2. Pros: low latency.
3. Cons: weaker cost reduction.

Option C (hybrid, recommended):
1. Flush when `batch_size==4` OR `oldest_age>=timeout`.
2. If timeout hits with 1-3 images, build partial 2x2 with blank tiles (`pad` mode) and one API call.
3. Add `single_fallback` mode as optional behavior for very low volume.

Asynchronous arrivals handling:
1. Build queue from filesystem scan order by file mtime (global FIFO), not per-request memory only.
2. Keep per-image metadata in memory during cycle and derive recoverability from files still unprocessed.
3. Use existing processed move strategy to guarantee at-least-once until completed.
4. Optional enhancement: `.processing` marker files to prevent duplicate work if future parallel workers are introduced.

## Mathematical Logic for Coordinate Translation
Assume a 2x2 mosaic with equal tiles:
1. Mosaic size: `Wm = 2*Wt`, `Hm = 2*Ht`.
2. Rekognition bbox (relative): `Left=l`, `Top=t`, `Width=w`, `Height=h` in `[0,1]`.
3. Convert to mosaic pixels:
```text
x1m = l * Wm
y1m = t * Hm
x2m = (l + w) * Wm
y2m = (t + h) * Hm
```
4. Determine quadrant by bbox centroid:
```text
cx = (x1m + x2m)/2
cy = (y1m + y2m)/2
col = clamp(floor(cx / Wt), 0, 1)
row = clamp(floor(cy / Ht), 0, 1)
tile_index = row*2 + col   # 0=TL,1=TR,2=BL,3=BR
```
5. Convert to tile-local coordinates:
```text
x1t = x1m - col*Wt
y1t = y1m - row*Ht
x2t = x2m - col*Wt
y2t = y2m - row*Ht
clip to [0, Wt] x [0, Ht]
```
6. If letterbox is used per tile (recommended), reverse to original image coordinates:
```text
scale = min(Wt/Wo, Ht/Ho)
Wr = Wo*scale
Hr = Ho*scale
pad_x = (Wt - Wr)/2
pad_y = (Ht - Hr)/2

x_orig = (x_tile - pad_x) / scale
y_orig = (y_tile - pad_y) / scale
clip to [0, Wo] x [0, Ho]
```

Example:
1. Tile size `Wt=640`, `Ht=480`, mosaic `1280x960`.
2. Rekognition returns `l=0.62, t=0.10, w=0.10, h=0.20`.
3. Mosaic pixels: `x1m=793.6, y1m=96, x2m=921.6, y2m=288`.
4. Centroid `(857.6,192)` => `col=1,row=0` (top-right tile).
5. Tile-local bbox: `x1t=153.6, y1t=96, x2t=281.6, y2t=288`.
6. Apply reverse letterbox transform to map into that tile's original camera frame.

## Resolution and 5MB Payload Constraints
Hard constraints to enforce:
1. Final encoded mosaic bytes must be `<= 5_242_880` (5MB).
2. Avoid additional downscale unless required for payload fit.
3. Keep tile dimensions high enough to preserve small-object detectability.

Recommended encoding strategy:
1. Build mosaic from 4 tiles at configured `Wt/Ht` using letterbox.
2. JPEG encode with starting quality (e.g. 90).
3. If payload >5MB, binary-search quality down to min quality (e.g. 45).
4. If still >5MB, downscale mosaic gradually (e.g. factor 0.9) with floor limits.
5. If still >5MB at minimum size/quality, split into 2x1 requests as safety fallback.

5% object-size guard:
1. Because 2x2 reduces each source object's relative area in the combined frame, do not additionally shrink tile input aggressively.
2. Introduce a minimum tile resolution threshold and bypass tiling for low-resolution sources.
3. Add metric logging: estimated projected bbox ratio after reverse mapping and detection hit rate by source resolution bucket.

## Proposed File Structure Additions or Changes
Existing files to change:
1. `services/yolo-worker-vm/src/worker/main.py` for batch orchestration path.
2. `services/yolo-worker-vm/src/worker/detector_rekognition.py` to add batch API and shared parsing.
3. `services/yolo-worker-vm/src/worker/config.py` for batch/tile/timeout/payload envs.
4. `services/.env.example` for new knobs.
5. `services/docker-compose.yml` to expose new worker env vars.

New files recommended:
1. `services/yolo-worker-vm/src/worker/mosaic_builder.py`
2. `services/yolo-worker-vm/src/worker/mosaic_mapper.py`
3. `services/yolo-worker-vm/src/worker/batch_queue.py`
4. `services/yolo-worker-vm/src/worker/types_mosaic.py` (optional typed payload models)
5. `services/yolo-worker-vm/tests/test_mosaic_mapper.py`
6. `services/yolo-worker-vm/tests/test_mosaic_builder_payload_limit.py`
7. `services/yolo-worker-vm/tests/test_batch_grouping_timeout.py`

## Step-by-Step Implementation Phases
Phase 1: Config and data contracts
1. Add envs for batch size, timeout, tile size, max payload, JPEG quality bounds, and fallback behavior.
2. Add internal dataclasses for `PendingImage`, `TileMeta`, `BatchMeta`, `MappedDetection`.

Phase 2: Mosaic generation and reverse mapping core
1. Implement 2x2 compositor with letterbox metadata capture.
2. Implement payload-limit loop to guarantee <=5MB.
3. Implement reverse-mapping functions and quadrant assignment by centroid.
4. Add unit tests for coordinate math and clipping rules.

Phase 3: Worker integration
1. In `scan_and_process`, build pending image list across devices with camera linkage.
2. Apply hybrid grouping (`count OR timeout`) and partial-batch padding policy.
3. Call one Rekognition request per batch and fan out detections to original images.
4. For each original image, run existing persistence path (`insert_detection`, offenders, notifications) with mapped camera context.
5. Keep existing per-device state updates (`last_count`) based on per-image mapped results.

Phase 4: Safety and edge-case handling
1. Define behavior for 1-3 images on timeout (`pad` default).
2. Handle unreadable image files by skipping and marking error log.
3. Handle detections crossing quadrant borders by centroid assignment + clipped bbox.
4. Handle no camera mapping (`resolve_camera=None`) exactly as current behavior (skip DB write, log debug).

Phase 5: Validation
1. Unit tests for translation formulas and letterbox inversion.
2. Integration test with synthetic known boxes in each quadrant.
3. Load test with asynchronous mixed device uploads.
4. Compare cost/latency vs per-image baseline and verify detection quality impact.

Phase 6: Controlled rollout
1. Feature flag: `REKOGNITION_MOSAIC_ENABLED`.
2. Start with shadow metrics mode (build mosaic + map, optionally still run per-image for comparison in non-prod).
3. Enable full mode after acceptance thresholds on recall/precision and payload compliance.

## Recommended Initial Defaults
1. `REKOGNITION_MOSAIC_ENABLED=true`
2. `REKOGNITION_MOSAIC_BATCH_SIZE=4`
3. `REKOGNITION_MOSAIC_TIMEOUT_SECONDS=8`
4. `REKOGNITION_MOSAIC_TILE_WIDTH=960`
5. `REKOGNITION_MOSAIC_TILE_HEIGHT=720`
6. `REKOGNITION_MOSAIC_MAX_PAYLOAD_BYTES=5242880`
7. `REKOGNITION_MOSAIC_JPEG_QUALITY_START=90`
8. `REKOGNITION_MOSAIC_JPEG_QUALITY_MIN=45`
9. `REKOGNITION_MOSAIC_PARTIAL_MODE=pad`
