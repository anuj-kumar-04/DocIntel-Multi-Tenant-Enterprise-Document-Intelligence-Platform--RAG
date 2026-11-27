import io
import re
from typing import Any

import numpy as np
from app.core.logging import logger

_ocr_engine: Any = None
_ocr_init_attempted = False

_DEFAULT_MIN_CONFIDENCE = 0.45
_MAX_OCR_SIDE_PX = 3600


def _get_ocr_engine() -> Any | None:
    """Lazy-load singleton RapidOCR ONNX engine (loaded only when scanned/image pages appear)."""
    global _ocr_engine, _ocr_init_attempted
    if _ocr_init_attempted:
        return _ocr_engine
    _ocr_init_attempted = True

    try:
        from rapidocr import RapidOCR

        _ocr_engine = RapidOCR()
        logger.info("RapidOCR ONNX engine initialized for scanned/image PDF extraction")
    except Exception as e:
        logger.warning(f"RapidOCR unavailable ({e}). Attempting rapidocr_onnxruntime fallback...")
        try:
            from rapidocr_onnxruntime import RapidOCR as RapidOCRLegacy

            _ocr_engine = RapidOCRLegacy()
            logger.info("RapidOCR legacy ONNX engine initialized")
        except Exception as e2:
            logger.warning(f"No OCR engine available ({e2}); scanned/image OCR skipped.")
            _ocr_engine = None
    return _ocr_engine


def _decode_image_rgb(image_bytes: bytes) -> np.ndarray | None:
    """Decode PNG/JPEG/TIFF bytes into an RGB numpy array handling transparency cleanly."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                composited = Image.alpha_composite(bg, rgba).convert("RGB")
                return np.array(composited)
            return np.array(img.convert("RGB"))
    except Exception:
        try:
            import cv2

            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is not None:
                return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        except Exception as e:
            logger.debug(f"Failed to decode image bytes for OCR: {e}")
    return None


def _estimate_skew_angle(gray: np.ndarray) -> float:
    """Estimate text skew angle in degrees (-15..15) via horizontal projection variance."""
    import cv2

    h, w = gray.shape
    if min(h, w) < 60:
        return 0.0

    # Downscale binary foreground map for fast (<10ms) angle scoring
    scale = min(1.0, 420.0 / max(h, w))
    small = (
        cv2.resize(
            gray, (max(40, int(w * scale)), max(40, int(h * scale))), interpolation=cv2.INTER_AREA
        )
        if scale < 1.0
        else gray
    )
    _, binary = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    fg_ratio = float(np.count_nonzero(binary)) / float(binary.size)
    if fg_ratio < 0.003 or fg_ratio > 0.65:
        return 0.0

    sh, sw = binary.shape
    center = (sw / 2.0, sh / 2.0)

    def score_angle(deg: float) -> float:
        if deg == 0.0:
            rotated = binary
        else:
            mat = cv2.getRotationMatrix2D(center, deg, 1.0)
            rotated = cv2.warpAffine(binary, mat, (sw, sh), flags=cv2.INTER_NEAREST, borderValue=0)
        row_sums = rotated.sum(axis=1, dtype=np.float64)
        return float(np.var(row_sums))

    zero_score = score_angle(0.0)
    if zero_score <= 0.0:
        return 0.0

    # Coarse scan (-14..+14 step 2), then refine (+/- 1.5 step 0.5)
    best_angle = 0.0
    best_score = zero_score
    for deg in range(-14, 15, 2):
        if deg == 0:
            continue
        sc = score_angle(float(deg))
        if sc > best_score:
            best_score = sc
            best_angle = float(deg)

    if best_angle != 0.0:
        center_coarse = best_angle
        for step in (-1.5, -1.0, -0.5, 0.5, 1.0, 1.5):
            cand = center_coarse + step
            if abs(cand) <= 15.0:
                sc = score_angle(cand)
                if sc > best_score:
                    best_score = sc
                    best_angle = cand

    # Rotate only when skew is real (>= 1.0 deg) and clearly sharpens text rows (+5%)
    if abs(best_angle) >= 1.0 and best_score > zero_score * 1.05:
        return best_angle
    return 0.0


def _preprocess_for_ocr(rgb: np.ndarray) -> np.ndarray:
    """Enhance noisy, faded, small, or slightly skewed scans before OCR inference."""
    try:
        import cv2
    except ImportError:
        return rgb

    h, w = rgb.shape[:2]

    # Guard memory on oversized canvases, or upscale tiny cropped raster graphics
    max_dim = max(h, w)
    min_dim = min(h, w)
    if max_dim > _MAX_OCR_SIDE_PX:
        ratio = _MAX_OCR_SIDE_PX / float(max_dim)
        rgb = cv2.resize(rgb, (int(w * ratio), int(h * ratio)), interpolation=cv2.INTER_AREA)
    elif min_dim < 220 or h < 90:
        rgb = cv2.resize(rgb, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # Detect impulse/speckle noise and denoise only when speckled; preserve crisp clean glyphs
    med = cv2.medianBlur(gray, 3)
    diff = cv2.absdiff(gray, med)
    noisy_fraction = float(np.count_nonzero(diff > 28)) / float(gray.size)
    if noisy_fraction > 0.008:
        gray = med

    # Apply CLAHE only on faded/low-contrast scans so crisp high-contrast text stays razor-sharp
    dynamic_range = float(np.percentile(gray, 95) - np.percentile(gray, 5))
    enhanced = (
        cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        if dynamic_range < 130.0
        else gray
    )

    angle = _estimate_skew_angle(enhanced)
    if angle != 0.0:
        eh, ew = enhanced.shape
        mat = cv2.getRotationMatrix2D((ew / 2.0, eh / 2.0), angle, 1.0)
        enhanced = cv2.warpAffine(
            enhanced,
            mat,
            (ew, eh),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255,
        )

    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)


def _format_ocr_result(raw_result: Any, min_confidence: float) -> str:
    """Normalize RapidOCR v2/v3 or legacy tuple output into reading-order lines."""
    items: list[tuple[Any, str, float]] = []

    if raw_result is None:
        return ""

    # RapidOCR >= 2.x returns RapidOCROutput with .boxes, .txts, .scores
    if hasattr(raw_result, "txts"):
        txts = getattr(raw_result, "txts", None) or []
        boxes = getattr(raw_result, "boxes", None)
        scores = getattr(raw_result, "scores", None) or []
        for idx, txt in enumerate(txts):
            clean = re.sub(r"\s+", " ", str(txt or "")).strip()
            if not clean:
                continue
            conf = float(scores[idx]) if idx < len(scores) and scores[idx] is not None else 1.0
            if conf < min_confidence:
                continue
            box = boxes[idx] if boxes is not None and idx < len(boxes) else None
            items.append((box, clean, conf))
    else:
        # Legacy rapidocr_onnxruntime returns ([[box, text, score], ...], elapse)
        rows = raw_result[0] if isinstance(raw_result, tuple) else raw_result
        if isinstance(rows, list):
            for entry in rows:
                if not entry or len(entry) < 2:
                    continue
                box, txt = entry[0], entry[1]
                conf = float(entry[2]) if len(entry) > 2 and entry[2] is not None else 1.0
                clean = re.sub(r"\s+", " ", str(txt or "")).strip()
                if clean and conf >= min_confidence:
                    items.append((box, clean, conf))

    if not items:
        return ""

    # Compute y-center, height, and x-left to reconstruct horizontal lines cleanly
    positioned: list[tuple[float, float, float, str]] = []
    heights: list[float] = []
    for idx, (box, text_val, _) in enumerate(items):
        if box is not None and len(box) >= 4:
            xs = [float(pt[0]) for pt in box]
            ys = [float(pt[1]) for pt in box]
            y_mid = (min(ys) + max(ys)) / 2.0
            x_left = min(xs)
            heights.append(max(8.0, max(ys) - min(ys)))
            positioned.append((y_mid, x_left, float(idx), text_val))
        else:
            positioned.append((float(idx) * 20.0, 0.0, float(idx), text_val))

    line_tol = (float(np.median(heights)) * 0.55) if heights else 12.0
    positioned.sort(key=lambda t: (t[0], t[1]))

    lines: list[list[tuple[float, str]]] = []
    current_y: float | None = None
    for y_mid, x_left, _, text_val in positioned:
        if current_y is None or abs(y_mid - current_y) > line_tol:
            lines.append([(x_left, text_val)])
            current_y = y_mid
        else:
            lines[-1].append((x_left, text_val))

    merged_lines = []
    for row in lines:
        row.sort(key=lambda col: col[0])
        joined = " ".join(part for _, part in row).strip()
        if joined:
            merged_lines.append(joined)

    return "\n".join(merged_lines)


class OCRService:
    """High-DPI OCR service built on lightweight ONNX RapidOCR with scan preprocessing."""

    @staticmethod
    def extract_text_from_image(
        image_bytes: bytes, min_confidence: float = _DEFAULT_MIN_CONFIDENCE
    ) -> str:
        """Extract clean reading-order text from raw image bytes (PNG/JPEG/TIFF)."""
        if not image_bytes:
            return ""

        engine = _get_ocr_engine()
        if engine is None:
            return ""

        rgb = _decode_image_rgb(image_bytes)
        if rgb is None or rgb.size == 0:
            return ""

        processed = _preprocess_for_ocr(rgb)
        try:
            res = engine(processed)
            text = _format_ocr_result(res, min_confidence=min_confidence)
            if text:
                return text
        except Exception as e:
            logger.debug(f"Preprocessed OCR pass notice: {e}")

        # Retry on raw RGB array if preprocessing trimmed sparse faint strokes
        try:
            res_raw = engine(rgb)
            return _format_ocr_result(res_raw, min_confidence=min_confidence)
        except Exception as e:
            logger.warning(f"OCR inference failed on image region: {e}")
            return ""


ocr_service = OCRService()
