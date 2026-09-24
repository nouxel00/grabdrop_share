"""Démo webcam : affiche la posture détectée et les événements GRAB / DROP, sans réseau.

Lancement :  python -m grabdrop.demo
Touches   :  q ou Échap pour quitter
"""

from __future__ import annotations

import argparse

from grabdrop.camera import add_camera_arguments, run_camera_loop


def main() -> None:
    p = argparse.ArgumentParser(description="GrabDrop : démo de détection des gestes grab/drop")
    add_camera_arguments(p)
    args = p.parse_args()
    print("Main ouverte -> poing = GRAB ; poing -> main ouverte = DROP. 'q' pour quitter.")
    run_camera_loop(args, title="GrabDrop demo - q pour quitter")


if __name__ == "__main__":
    main()
