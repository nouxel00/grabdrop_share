"""Calculs géométriques sur les 21 points de la main (sans dépendance à MediaPipe).

Numérotation MediaPipe : 0 = poignet, 1-4 = pouce, 5-8 = index, 9-12 = majeur,
13-16 = annulaire, 17-20 = auriculaire (dans chaque doigt : MCP, PIP, DIP, bout).
"""

from __future__ import annotations

import math
from typing import Sequence

from grabdrop.gestures import Posture

WRIST, INDEX_MCP, PINKY_MCP = 0, 5, 17
# (PIP, bout) pour index, majeur, annulaire, auriculaire. Le pouce est ignoré.
FINGERS = ((6, 8), (10, 12), (14, 16), (18, 20))

# Rapport distance(poignet, bout) / distance(poignet, PIP) :
# ~1,35 pour un doigt tendu, ~1,05 pour un doigt en griffe, < 0,8 dans un poing.
EXTENDED_RATIO = 1.15
CURLED_RATIO = 0.9

Point = Sequence[float]


def finger_ratios(points: Sequence[Point]) -> list[float]:
    wrist = points[WRIST]
    return [math.dist(wrist, points[tip]) / max(math.dist(wrist, points[pip]), 1e-6) for pip, tip in FINGERS]


def extended_fingers(points: Sequence[Point]) -> int:
    return sum(r > EXTENDED_RATIO for r in finger_ratios(points))


def posture_from_landmarks(points: Sequence[Point]) -> Posture:
    """Posture déduite des points 3D (de préférence les « world landmarks », en mètres)."""
    ratios = finger_ratios(points)
    extended = sum(r > EXTENDED_RATIO for r in ratios)
    curled = sum(r < CURLED_RATIO for r in ratios)
    if extended == 4:
        return Posture.OPEN
    if extended == 0 and curled >= 3:
        return Posture.FIST
    return Posture.NONE


def combine_postures(geometric: Posture, classifier: Posture) -> Posture:
    """Fusionne les deux avis : l'un suffit, mais s'ils se contredisent on s'abstient."""
    if classifier == Posture.NONE or geometric == classifier:
        return geometric
    if geometric == Posture.NONE:
        return classifier
    return Posture.NONE


def palm_facing_camera(points_2d: Sequence[Point], handedness: str) -> bool:
    """Vrai si la paume est tournée vers la caméra.

    `points_2d` : coordonnées image (x vers la droite, y vers le bas) d'une image
    en miroir ; `handedness` : "Right" ou "Left" tel que renvoyé par MediaPipe.

    Vraie main droite paume face caméra, vue en miroir : l'index est à gauche de
    l'auriculaire (vu depuis le poignet), ce qui donne un produit vectoriel positif.
    Le signe s'inverse pour une main gauche ou quand on voit le dos de la main.

    Attention : sur une image en miroir, MediaPipe renvoie l'étiquette inverse de
    la vraie main (vérifié sur les images d'exemple MediaPipe) : une vraie main
    droite y est étiquetée "Left".
    """
    wx, wy = points_2d[WRIST][:2]
    ax, ay = points_2d[INDEX_MCP][0] - wx, points_2d[INDEX_MCP][1] - wy
    bx, by = points_2d[PINKY_MCP][0] - wx, points_2d[PINKY_MCP][1] - wy
    cross = ax * by - ay * bx
    is_real_right_hand = handedness == "Left"
    return (cross > 0) == is_real_right_hand
