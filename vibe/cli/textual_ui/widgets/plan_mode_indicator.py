from __future__ import annotations

from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic


class PlanModeIndicator(NoMarkupStatic):
    """Static `[PLAN]` chip rendered in the bottom bar while plan mode is
    active. Hidden otherwise. Updated via `set_active(bool)` from the app's
    profile-change callback.
    """

    def __init__(self) -> None:
        super().__init__()
        self.can_focus = False
        self._active = False
        self._update_display()

    def _update_display(self) -> None:
        self.update("[PLAN]" if self._active else "")
        self.display = self._active

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self._update_display()
