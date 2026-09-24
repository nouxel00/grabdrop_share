"""Démo webcam : affiche la posture détectée et les événements GRAB / DROP, sans réseau.

Lancement :  python -m grabdrop.demo
Touches   :  q ou Échap pour quitter
"""

from __future__ import annotations

import argparse
import logging

from grabdrop.camera import CameraControls, add_camera_arguments, run_camera_loop


def main() -> None:
    p = argparse.ArgumentParser(description="GrabDrop : démo de détection des gestes grab/drop")
    add_camera_arguments(p)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    print("Main ouverte -> poing = GRAB ; poing -> main ouverte = DROP. 'q' pour quitter.")
    run_camera_loop(args, controls=CameraControls(preview=True), title="GrabDrop demo - q pour quitter")


if __name__ == "__main__":
    main()
