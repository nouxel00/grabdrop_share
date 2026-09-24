from grabdrop.gestures import Posture
from grabdrop.hand_geometry import combine_postures, extended_fingers, palm_facing_camera, posture_from_landmarks

O, F, N = Posture.OPEN, Posture.FIST, Posture.NONE
FINGER_X = (-0.03, -0.01, 0.01, 0.03)  # index, majeur, annulaire, auriculaire


def hand(tip_y_per_finger):
    """Main synthétique en mètres, poignet à l'origine, doigts vers le haut (y négatif).

    `tip_y_per_finger` : position verticale du bout de chaque doigt (hors pouce).
    """
    pts = [(0.0, 0.0, 0.0)] * 21
    pts = list(pts)
    for i in range(1, 5):  # pouce, sans importance ici
        pts[i] = (-0.04, -0.03 * i / 4, 0.0)
    for f, (x, tip_y) in enumerate(zip(FINGER_X, tip_y_per_finger)):
        mcp = 5 + 4 * f
        pts[mcp] = (x, -0.09, 0.0)
        pts[mcp + 1] = (x, -0.13, 0.0)  # PIP
        pts[mcp + 2] = (x, (-0.13 + tip_y) / 2, 0.0)  # DIP
        pts[mcp + 3] = (x, tip_y, 0.0)  # bout
    return pts


OPEN_HAND = hand([-0.175] * 4)
FIST = hand([-0.06] * 4)
CLAW = hand([-0.138] * 4)  # doigts à moitié repliés
POINTING = hand([-0.175, -0.06, -0.06, -0.06])


def test_open_hand():
    assert extended_fingers(OPEN_HAND) == 4
    assert posture_from_landmarks(OPEN_HAND) == O


def test_fist():
    assert extended_fingers(FIST) == 0
    assert posture_from_landmarks(FIST) == F


def test_ambiguous_shapes_are_none():
    assert posture_from_landmarks(CLAW) == N
    assert posture_from_landmarks(POINTING) == N


def test_combine_postures():
    assert combine_postures(O, N) == O
    assert combine_postures(N, F) == F
    assert combine_postures(O, O) == O
    assert combine_postures(O, F) == N  # avis contradictoires


def _mirror(points):
    return [(-x, y, z) for x, y, z in points]


# Sur une image en miroir, MediaPipe étiquette la vraie main droite "Left" (et inversement).
REAL_RIGHT, REAL_LEFT = "Left", "Right"


def test_palm_orientation():
    # Vraie main droite paume face caméra (image en miroir) : index à gauche, auriculaire à droite.
    right_palm = OPEN_HAND
    assert palm_facing_camera(right_palm, REAL_RIGHT)
    # Même main vue de dos : l'index passe à droite.
    assert not palm_facing_camera(_mirror(right_palm), REAL_RIGHT)
    # Main gauche : tout s'inverse.
    assert palm_facing_camera(_mirror(right_palm), REAL_LEFT)
    assert not palm_facing_camera(right_palm, REAL_LEFT)


def test_palm_orientation_is_rotation_invariant():
    # Vraie main droite paume face caméra, doigts vers la gauche (rotation de 90°).
    rotated = [(y, -x, z) for x, y, z in OPEN_HAND]
    assert palm_facing_camera(rotated, REAL_RIGHT)
