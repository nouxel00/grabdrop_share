from grabdrop.gestures import Event, GestureConfig, GestureStateMachine, Posture

O, F, N = Posture.OPEN, Posture.FIST, Posture.NONE
FRAME_MS = 50  # ~20 fps


def run(sequence, config=None):
    """sequence : liste de (posture, durée_ms). Renvoie [(t_ms, événement)]."""
    sm = GestureStateMachine(config or GestureConfig())
    events, t = [], 0
    for posture, duration in sequence:
        for _ in range(duration // FRAME_MS):
            ev = sm.update(posture, t)
            if ev:
                events.append((t, ev))
            t += FRAME_MS
    return [ev for _, ev in events]


def test_open_then_fist_is_grab():
    assert run([(O, 600), (F, 600)]) == [Event.GRAB]


def test_fist_then_open_is_drop():
    assert run([(F, 600), (O, 600)]) == [Event.DROP]


def test_single_posture_triggers_nothing():
    assert run([(F, 3000)]) == []
    assert run([(O, 3000)]) == []


def test_short_postures_are_ignored():
    # Poing trop bref pour être stable.
    assert run([(O, 600), (F, 150), (O, 600)]) == []


def test_ambiguous_frames_during_transition_are_tolerated():
    assert run([(O, 600), (N, 300), (F, 600)]) == [Event.GRAB]


def test_too_long_gap_breaks_transition():
    # La main disparaît 2 s : ce n'est plus un geste continu.
    assert run([(O, 600), (N, 2000), (F, 600)]) == []


def test_quick_grab_then_drop():
    # Cas qui échouait avec l'ancien délai de 1,5 s : le DROP était perdu.
    assert run([(O, 600), (F, 400), (O, 600)]) == [Event.GRAB, Event.DROP]


def test_cooldown_delays_event_instead_of_dropping_it():
    long_cooldown = GestureConfig(cooldown_ms=1500)
    # GRAB à 900 ms ; main rouverte tenue 2 s : DROP émis à la fin du délai.
    assert run([(O, 600), (F, 400), (O, 2000)], long_cooldown) == [Event.GRAB, Event.DROP]
    # Main rouverte trop brièvement : pas de DROP.
    assert run([(O, 600), (F, 400), (O, 500), (N, 1500)], long_cooldown) == [Event.GRAB]


def test_grab_then_drop_after_long_hold():
    assert run([(O, 600), (F, 2000), (O, 600)]) == [Event.GRAB, Event.DROP]


def test_brief_flicker_does_not_reset_stable_posture():
    # Une image mal classée au milieu d'une main ouverte ne casse rien.
    assert run([(O, 400), (N, 50), (O, 400), (F, 600)]) == [Event.GRAB]
