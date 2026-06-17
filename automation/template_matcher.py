"""OpenCV template matching against a screenshot, for locating buttons/popups."""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Match:
    name: str
    confidence: float
    center: tuple[int, int]


def load_gray(path):
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def find(screenshot_gray, template_gray, name, threshold=0.8):
    result = cv2.matchTemplate(screenshot_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    h, w = template_gray.shape
    center = (max_loc[0] + w // 2, max_loc[1] + h // 2)
    return Match(name=name, confidence=max_val, center=center)


def find_best(screenshot_gray, templates: dict, threshold=0.8):
    """templates: {name: template_gray}. Returns the highest-confidence Match or None."""
    best = None
    for name, template_gray in templates.items():
        m = find(screenshot_gray, template_gray, name, threshold=threshold)
        if m and (best is None or m.confidence > best.confidence):
            best = m
    return best


def find_multiscale(screenshot_gray, template_gray, name, threshold=0.8, scales=None):
    """Like find(), but also tries resizing the template across `scales`.

    Useful when the template was cropped from a reference image captured at a
    different resolution/aspect ratio than the live screenshot, so the exact
    pixel size of the on-screen element isn't known in advance.
    """
    if scales is None:
        scales = [round(s, 2) for s in np.arange(0.6, 1.41, 0.05)]

    best = None
    h, w = template_gray.shape
    for scale in scales:
        resized = cv2.resize(template_gray, (max(1, int(w * scale)), max(1, int(h * scale))))
        if resized.shape[0] > screenshot_gray.shape[0] or resized.shape[1] > screenshot_gray.shape[1]:
            continue
        m = find(screenshot_gray, resized, name, threshold=threshold)
        if m and (best is None or m.confidence > best.confidence):
            best = m
    return best
