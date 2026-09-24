"""Machine à états qui transforme des postures de main en événements GRAB / DROP.

Indépendante de la caméra et de MediaPipe : on lui donne une posture par image
(avec un horodatage), elle renvoie un événement quand une transition valide
est détectée. C'est ce qui permet de la tester sans webcam.

- GRAB : main ouverte (stable) -> poing fermé (tenu `hold_ms`)
- DROP : poing fermé (stable) -> main ouverte (tenue `hold_ms`)

Exiger une transition (et pas une simple posture) limite fortement les faux
positifs : un poing seul ou une main levée ne déclenchent rien.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Posture(str, Enum):
    OPEN = "open"
    FIST = "fist"
    NONE = "none"  # pas de main, ou geste non pertinent


class Event(str, Enum):
    GRAB = "grab"
    DROP = "drop"


@dataclass
class GestureConfig:
    # Durée pendant laquelle une posture doit être tenue pour être "stable".
    hold_ms: int = 300
    # Délai max entre la dernière image de la posture de départ et la première
    # image de la posture d'arrivée (la fermeture de la main passe par des
    # images ambiguës classées NONE).
    transition_ms: int = 800
    # Délai minimal entre deux événements, pour éviter les rafales. Un événement
    # qui tombe pendant ce délai est retardé (si la posture est tenue), pas perdu.
    cooldown_ms: int = 600


class GestureStateMachine:
    def __init__(self, config: GestureConfig | None = None) -> None:
        self.config = config or GestureConfig()
        self._current = Posture.NONE
        self._current_since = 0
        # Dernière posture stable (OPEN ou FIST) et dernier instant où on l'a vue.
        self._stable = Posture.NONE
        self._stable_last_seen = 0
        self._last_event_at: int | None = None

    @property
    def stable_posture(self) -> Posture:
        return self._stable

    def update(self, posture: Posture, now_ms: int) -> Event | None:
        cfg = self.config

        if posture != self._current:
            self._current = posture
            self._current_since = now_ms

        if posture == Posture.NONE:
            return None
        if posture == self._stable:
            self._stable_last_seen = now_ms
            return None
        if now_ms - self._current_since < cfg.hold_ms:
            return None

        # Nouvelle posture stable, différente de la précédente.
        previous = self._stable
        gap = self._current_since - self._stable_last_seen
        is_transition = previous != Posture.NONE and gap <= cfg.transition_ms
        in_cooldown = self._last_event_at is not None and now_ms - self._last_event_at < cfg.cooldown_ms
        if is_transition and in_cooldown:
            # On ne valide pas encore la nouvelle posture : l'événement sera émis
            # à la fin du délai si la posture est toujours tenue.
            return None

        self._stable = posture
        self._stable_last_seen = now_ms
        if not is_transition:
            return None

        self._last_event_at = now_ms
        return Event.GRAB if posture == Posture.FIST else Event.DROP
