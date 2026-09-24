"""Boucle caméra partagée par la démo et l'agent : détection, gestes, aperçu."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from typing import Callable

import cv2
from mediapipe.tasks.python.vision import HandLandmarksConnections

from grabdrop.detector import HandPostureDetector, HandReading
from grabdrop.gestures import Event, GestureConfig, GestureStateMachine, Posture

BANNER_MS = 1200

# Couleurs BGR
GREEN, ORANGE, GREY, WHITE, BLUE = (80, 200, 80), (0, 160, 255), (160, 160, 160), (255, 255, 255), (255, 140, 40)
POSTURE_COLOR = {Posture.OPEN: GREEN, Posture.FIST: ORANGE, Posture.NONE: GREY}


def add_camera_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--camera", type=int, default=0, help="index de la webcam (défaut : 0)")
    p.add_argument("--min-score", type=float, default=0.6, help="confiance minimale du modèle")
    p.add_argument("--hold-ms", type=int, default=GestureConfig.hold_ms, help="durée de tenue d'une posture")
    p.add_argument("--allow-back", action="store_true", help="accepter la main ouverte vue de dos")
    p.add_argument(
        "--min-hand-size", type=float, default=0.10,
        help="taille min. de la main (~0,1 = 1 m de la caméra ; augmenter si un PC voisin réagit à vos gestes)",
    )
    p.add_argument("--log", metavar="FICHIER.csv", help="enregistrer chaque image analysée (pour le réglage)")


def open_camera(index: int) -> cv2.VideoCapture:
    # DirectShow ouvre la webcam bien plus vite que le backend par défaut sous Windows.
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        sys.exit(f"Impossible d'ouvrir la caméra {index} (déjà utilisée par une autre application ?)")
    return cap


def run_camera_loop(
    args: argparse.Namespace,
    on_event: Callable[[Event], None] | None = None,
    preview: bool = True,
    title: str = "GrabDrop - q pour quitter",
    status: Callable[[], str] | None = None,
) -> None:
    """Analyse la webcam jusqu'à 'q' / Échap (avec aperçu) ou Ctrl+C (sans aperçu).

    `on_event` est appelé dans cette boucle : il doit rendre la main rapidement.
    """
    detector = HandPostureDetector(
        min_score=args.min_score, require_palm=not args.allow_back, min_hand_size=args.min_hand_size
    )
    machine = GestureStateMachine(GestureConfig(hold_ms=args.hold_ms))
    cap = open_camera(args.camera)
    log = open(args.log, "w", newline="", encoding="utf-8") if args.log else None
    log_writer = csv.writer(log) if log else None
    if log_writer:
        log_writer.writerow(
            ["t_ms", "categorie", "score", "main", "paume", "doigts", "taille", "posture", "stable", "evenement"]
        )

    last_event: tuple[Event, int] | None = None
    fps, last_t = 0.0, time.monotonic()

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Lecture caméra impossible, arrêt.")
                break
            frame = cv2.flip(frame, 1)  # effet miroir, plus naturel
            now_ms = int(time.monotonic() * 1000)

            reading = detector.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), now_ms)
            event = machine.update(reading.posture if reading else Posture.NONE, now_ms)
            if event:
                last_event = (event, now_ms)
                print(f"[{datetime.now():%H:%M:%S}] {event.value.upper()}")
                if on_event:
                    on_event(event)
            if log_writer:
                r = reading
                log_writer.writerow([
                    now_ms, r.category if r else "", f"{r.score:.2f}" if r else "", r.handedness if r else "",
                    int(r.palm_facing) if r else "", r.extended if r else "", f"{r.size:.3f}" if r else "",
                    r.posture.value if r else "none", machine.stable_posture.value, event.value if event else "",
                ])

            if not preview:
                continue

            t = time.monotonic()
            fps = 0.9 * fps + 0.1 * (1 / max(t - last_t, 1e-6))
            last_t = t
            if reading:
                _draw_hand(frame, reading)
            _draw_hud(frame, reading, machine.stable_posture, fps)
            if status:
                _draw_status(frame, status())
            if last_event and now_ms - last_event[1] < BANNER_MS:
                _draw_banner(frame, last_event[0])

            cv2.imshow(title, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27) or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
        detector.close()
        if log:
            log.close()
            print(f"Journal enregistré : {args.log}")


def _draw_hand(frame, reading: HandReading) -> None:
    h, w = frame.shape[:2]
    pts = [(int(x * w), int(y * h)) for x, y in reading.landmarks]
    color = POSTURE_COLOR[reading.posture]
    for c in HandLandmarksConnections.HAND_CONNECTIONS:
        cv2.line(frame, pts[c.start], pts[c.end], color, 2)
    for pt in pts:
        cv2.circle(frame, pt, 4, WHITE, -1)


def _draw_hud(frame, reading: HandReading | None, stable: Posture, fps: float) -> None:
    if reading:
        side = "paume" if reading.palm_facing else "dos"
        raw = f"{reading.category} ({reading.score:.2f}) | {reading.extended}/4 doigts | {side} | taille {reading.size:.2f}"
    else:
        raw = "aucune main"
    posture = reading.posture if reading else Posture.NONE
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 70), (30, 30, 30), -1)
    cv2.putText(frame, raw, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, POSTURE_COLOR[posture], 1)
    cv2.putText(frame, f"Posture stable : {stable.value}", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, POSTURE_COLOR[stable], 2)
    cv2.putText(frame, f"{fps:4.1f} fps", (frame.shape[1] - 90, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)


def _draw_status(frame, text: str) -> None:
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, h - 30), (w, h), (30, 30, 30), -1)
    cv2.putText(frame, text, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)


def _draw_banner(frame, event: Event) -> None:
    text = "GRAB !" if event == Event.GRAB else "DROP !"
    color = ORANGE if event == Event.GRAB else BLUE
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, h - 120), (w, h - 30), color, -1)
    (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.8, 4)
    cv2.putText(frame, text, ((w - tw) // 2, h - 58), cv2.FONT_HERSHEY_SIMPLEX, 1.8, WHITE, 4)
