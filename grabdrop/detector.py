"""Détection de posture de main à partir d'images caméra, via MediaPipe."""

from __future__ import annotations

import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from grabdrop.config import config_path
from grabdrop.gestures import Posture
from grabdrop.hand_geometry import (
    combine_postures,
    extended_fingers,
    hand_scale,
    palm_facing_camera,
    posture_from_landmarks,
)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/latest/gesture_recognizer.task"
)
# Hors du dépôt : GrabDrop peut être installé ailleurs (pip install -e . ou non).
MODEL_PATH = config_path().parent / "models" / "gesture_recognizer.task"

# Catégories du modèle MediaPipe -> nos postures.
_CATEGORY_TO_POSTURE = {
    "Open_Palm": Posture.OPEN,
    "Closed_Fist": Posture.FIST,
}


def ensure_model(path: Path = MODEL_PATH) -> Path:
    """Modèle livré avec l'exécutable (version installée), sinon téléchargé au premier lancement."""
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "models" / "gesture_recognizer.task"
    if getattr(sys, "frozen", False) and bundled.exists():
        return bundled
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Téléchargement du modèle de gestes -> {path}")
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)
        tmp.replace(path)
    return path


@dataclass
class HandReading:
    posture: Posture  # posture finale, après fusion et contrôle de la paume
    category: str  # catégorie brute du modèle (ex. "Closed_Fist", "Victory"...)
    score: float
    handedness: str  # "Right" / "Left"
    palm_facing: bool
    extended: int  # doigts tendus (hors pouce), 0 à 4
    size: float  # taille apparente de la paume (voir hand_scale)
    landmarks: list[tuple[float, float]]  # 21 points normalisés (0..1)


class HandPostureDetector:
    def __init__(
        self,
        min_score: float = 0.6,
        require_palm: bool = True,
        min_hand_size: float = 0.0,
        model_path: Path | None = None,
    ) -> None:
        self.min_score = min_score
        # Main ouverte acceptée seulement paume face à la caméra (comme Huawei).
        self.require_palm = require_palm
        # Main trop petite = trop loin : sans doute un geste destiné à un autre écran.
        self.min_hand_size = min_hand_size
        options = vision.GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path or ensure_model())),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
        )
        self._recognizer = vision.GestureRecognizer.create_from_options(options)

    def detect(self, rgb_frame: np.ndarray, timestamp_ms: int) -> HandReading | None:
        """Analyse une image RGB. Renvoie la main la plus grande (la plus proche), ou None."""
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._recognizer.recognize_for_video(image, timestamp_ms)
        if not result.hand_landmarks:
            return None

        # Plusieurs mains visibles : on garde celle qui occupe le plus de place.
        best = max(range(len(result.hand_landmarks)), key=lambda i: _area(result.hand_landmarks[i]))
        landmarks = [(lm.x, lm.y) for lm in result.hand_landmarks[best]]
        world = [(lm.x, lm.y, lm.z) for lm in result.hand_world_landmarks[best]]
        top = result.gestures[best][0] if result.gestures and result.gestures[best] else None
        category = top.category_name if top else "None"
        score = top.score if top else 0.0
        side = result.handedness[best][0].category_name if result.handedness and result.handedness[best] else "Right"

        # Deux avis indépendants : le classifieur MediaPipe (strict, aime les doigts
        # écartés) et la géométrie des doigts (tolère une main ouverte doigts serrés).
        from_classifier = _CATEGORY_TO_POSTURE.get(category, Posture.NONE) if score >= self.min_score else Posture.NONE
        posture = combine_postures(posture_from_landmarks(world), from_classifier)

        palm = palm_facing_camera(landmarks, side)
        if posture == Posture.OPEN and self.require_palm and not palm:
            posture = Posture.NONE
        size = hand_scale(landmarks, rgb_frame.shape[1], rgb_frame.shape[0])
        if size < self.min_hand_size:
            posture = Posture.NONE
        return HandReading(posture, category, score, side, palm, extended_fingers(world), size, landmarks)

    def close(self) -> None:
        self._recognizer.close()


def _area(landmarks) -> float:
    xs = [lm.x for lm in landmarks]
    ys = [lm.y for lm in landmarks]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))
