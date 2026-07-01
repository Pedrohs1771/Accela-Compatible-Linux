"""
LumaTools — Achievement Pacer para Safe Unlocking.

Controla o ritmo de desbloqueio de conquistas para parecer orgânico,
evitando detecção por padrões de desbloqueio instantâneo.

Inspirado no SAM (Steam Achievement Manager) e Achievement Abuser Enhanced.

Features:
- Intervalos aleatórios entre desbloqueios (3-15 min)
- Batch mode com cooldown entre lotes
- Time estimation para completar todas conquistas
- Verificação de perfil público/privado
- Suporte a reset individual e em lote
- Priorização por raridade (conquistas comuns primeiro)
"""

import logging
import random
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class PacerState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Achievement:
    """Representa uma conquista individual do Steam."""

    api_name: str
    display_name: str = ""
    description: str = ""
    icon_url: str = ""
    is_unlocked: bool = False
    unlock_time: Optional[datetime] = None
    global_percentage: float = 100.0  # Raridade (% de jogadores que desbloquearam)

    @property
    def is_rare(self) -> bool:
        return self.global_percentage < 10.0

    @property
    def is_common(self) -> bool:
        return self.global_percentage >= 50.0


@dataclass
class PacerProgress:
    """Status do progresso atual do pacer."""

    state: PacerState = PacerState.IDLE
    total_achievements: int = 0
    unlocked_count: int = 0
    remaining_count: int = 0
    current_achievement: str = ""
    estimated_remaining: Optional[timedelta] = None
    next_unlock_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)

    @property
    def progress_percent(self) -> float:
        if self.total_achievements == 0:
            return 0.0
        return (self.unlocked_count / self.total_achievements) * 100.0


class AchievementPacer:
    """Controla o ritmo de desbloqueio de conquistas para parecer orgânico.

    O pacer simula um padrão humano de desbloqueio, distribuindo conquistas
    ao longo do tempo com intervalos variáveis para evitar detecção.

    Configuração padrão:
    - 3-15 minutos entre cada conquista individual
    - Lotes de 5 conquistas
    - 30 minutos de cooldown entre lotes
    - Conquistas comuns primeiro, raras por último
    """

    # Default timing configuration
    MIN_DELAY_SECONDS = 180     # 3 minutos mínimo entre conquistas
    MAX_DELAY_SECONDS = 900     # 15 minutos máximo entre conquistas
    BATCH_SIZE = 5              # Conquistas por lote
    COOLDOWN_BETWEEN_BATCHES = 1800  # 30 min entre lotes
    JITTER_PERCENT = 0.3        # 30% de variação nos tempos

    def __init__(
        self,
        min_delay: int = MIN_DELAY_SECONDS,
        max_delay: int = MAX_DELAY_SECONDS,
        batch_size: int = BATCH_SIZE,
        cooldown: int = COOLDOWN_BETWEEN_BATCHES,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.batch_size = batch_size
        self.cooldown = cooldown

        self._state = PacerState.IDLE
        self._progress = PacerProgress()
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._progress_cb: Optional[Callable[[PacerProgress], None]] = None

    @property
    def state(self) -> PacerState:
        return self._state

    @property
    def progress(self) -> PacerProgress:
        return self._progress

    def start(
        self,
        achievements: List[Achievement],
        unlock_fn: Callable[[Achievement], bool],
        progress_cb: Optional[Callable[[PacerProgress], None]] = None,
        *,
        sort_by_rarity: bool = True,
    ) -> bool:
        """Inicia o desbloqueio paceado de conquistas.

        Parameters
        ----------
        achievements : list of Achievement
            Lista de conquistas a desbloquear. Apenas conquistas com
            ``is_unlocked=False`` serão processadas.
        unlock_fn : callable
            Função que recebe um ``Achievement`` e retorna ``True`` se
            o desbloqueio foi bem-sucedido.
        progress_cb : callable, optional
            Callback chamado após cada desbloqueio com um ``PacerProgress``.
        sort_by_rarity : bool
            Se True, desbloqueia conquistas comuns primeiro.

        Returns
        -------
        bool
            True se o pacer iniciou com sucesso.
        """
        if self._state == PacerState.RUNNING:
            logger.warning("Pacer already running")
            return False

        # Filter only locked achievements
        to_unlock = [a for a in achievements if not a.is_unlocked]
        if not to_unlock:
            logger.info("No locked achievements to process")
            return False

        # Sort by rarity (common first, rare last)
        if sort_by_rarity:
            to_unlock.sort(key=lambda a: -a.global_percentage)

        self._cancel_event.clear()
        self._pause_event.set()
        self._progress_cb = progress_cb

        self._progress = PacerProgress(
            state=PacerState.RUNNING,
            total_achievements=len(to_unlock),
            remaining_count=len(to_unlock),
        )
        self._state = PacerState.RUNNING

        self._thread = threading.Thread(
            target=self._run_paced_unlock,
            args=(to_unlock, unlock_fn),
            daemon=True,
            name=f"AchievementPacer-{id(self)}",
        )
        self._thread.start()
        logger.info(
            "Achievement Pacer started: %d achievements to unlock",
            len(to_unlock),
        )
        return True

    def pause(self) -> None:
        """Pause the pacer. Resume with resume()."""
        self._pause_event.clear()
        self._state = PacerState.PAUSED
        self._progress.state = PacerState.PAUSED
        logger.info("Achievement Pacer paused")

    def resume(self) -> None:
        """Resume a paused pacer."""
        self._pause_event.set()
        self._state = PacerState.RUNNING
        self._progress.state = PacerState.RUNNING
        logger.info("Achievement Pacer resumed")

    def cancel(self) -> None:
        """Cancel the pacer. Cannot be resumed."""
        self._cancel_event.set()
        self._pause_event.set()  # Wake up if paused
        self._state = PacerState.CANCELLED
        self._progress.state = PacerState.CANCELLED
        logger.info("Achievement Pacer cancelled")

    def estimate_total_time(self, achievement_count: int) -> timedelta:
        """Estimate total time to unlock N achievements.

        Parameters
        ----------
        achievement_count : int
            Number of achievements to unlock.

        Returns
        -------
        timedelta
            Estimated total time including batch cooldowns.
        """
        if achievement_count <= 0:
            return timedelta()

        avg_delay = (self.min_delay + self.max_delay) / 2.0
        total_delay = avg_delay * achievement_count

        # Add batch cooldowns
        num_batches = max(0, (achievement_count - 1) // self.batch_size)
        total_delay += num_batches * self.cooldown

        return timedelta(seconds=total_delay)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_paced_unlock(
        self,
        achievements: List[Achievement],
        unlock_fn: Callable[[Achievement], bool],
    ) -> None:
        """Worker thread that executes the paced unlocking."""
        batch_counter = 0

        for i, achievement in enumerate(achievements):
            # Check for cancellation
            if self._cancel_event.is_set():
                break

            # Check for pause
            self._pause_event.wait()

            if self._cancel_event.is_set():
                break

            # Update progress
            self._progress.current_achievement = (
                achievement.display_name or achievement.api_name
            )
            remaining = len(achievements) - i
            self._progress.remaining_count = remaining
            self._progress.estimated_remaining = self.estimate_total_time(remaining)

            # Calculate delay
            if i > 0:
                delay = self._calculate_delay(achievement, batch_counter)
                self._progress.next_unlock_at = datetime.now() + timedelta(
                    seconds=delay
                )
                self._notify_progress()

                # Wait with cancellation check
                if not self._interruptible_sleep(delay):
                    break

            # Attempt unlock
            try:
                success = unlock_fn(achievement)
                if success:
                    achievement.is_unlocked = True
                    achievement.unlock_time = datetime.now()
                    self._progress.unlocked_count += 1
                    logger.info(
                        "Unlocked achievement %d/%d: %s",
                        self._progress.unlocked_count,
                        self._progress.total_achievements,
                        achievement.display_name or achievement.api_name,
                    )
                else:
                    self._progress.errors.append(
                        f"Failed to unlock: {achievement.api_name}"
                    )
                    logger.warning(
                        "Failed to unlock: %s",
                        achievement.api_name,
                    )
            except Exception as exc:
                self._progress.errors.append(
                    f"Error unlocking {achievement.api_name}: {exc}"
                )
                logger.error(
                    "Exception unlocking %s: %s",
                    achievement.api_name,
                    exc,
                )

            batch_counter += 1

            # Batch cooldown
            if batch_counter >= self.batch_size:
                batch_counter = 0
                if i < len(achievements) - 1:
                    logger.info(
                        "Batch complete, cooldown for %d seconds",
                        self.cooldown,
                    )
                    if not self._interruptible_sleep(self.cooldown):
                        break

            self._notify_progress()

        # Finalize
        if self._cancel_event.is_set():
            self._state = PacerState.CANCELLED
            self._progress.state = PacerState.CANCELLED
        else:
            self._state = PacerState.COMPLETED
            self._progress.state = PacerState.COMPLETED
            self._progress.remaining_count = 0

        self._progress.next_unlock_at = None
        self._notify_progress()

        logger.info(
            "Achievement Pacer finished: %d/%d unlocked, state=%s",
            self._progress.unlocked_count,
            self._progress.total_achievements,
            self._state.value,
        )

    def _calculate_delay(self, achievement: Achievement, batch_pos: int) -> float:
        """Calculate delay before the next unlock.

        Applies jitter and adjustments based on achievement rarity.
        """
        base_delay = random.uniform(self.min_delay, self.max_delay)

        # Rare achievements get slightly longer delays (more organic)
        if achievement.is_rare:
            base_delay *= 1.5
        elif achievement.is_common:
            base_delay *= 0.8

        # Add random jitter
        jitter_range = base_delay * self.JITTER_PERCENT
        jitter = random.uniform(-jitter_range, jitter_range)

        # Increase delay slightly as we progress through a batch
        batch_factor = 1.0 + (batch_pos * 0.05)

        return max(30, (base_delay + jitter) * batch_factor)

    def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep that can be interrupted by cancellation.

        Returns
        -------
        bool
            True if the sleep completed normally, False if cancelled.
        """
        end_time = time.monotonic() + seconds
        while time.monotonic() < end_time:
            if self._cancel_event.is_set():
                return False
            self._pause_event.wait(timeout=0.5)
            if self._cancel_event.is_set():
                return False
        return True

    def _notify_progress(self) -> None:
        """Notify progress callback if set."""
        if self._progress_cb:
            try:
                self._progress_cb(self._progress)
            except Exception as exc:
                logger.debug("Progress callback error: %s", exc)
