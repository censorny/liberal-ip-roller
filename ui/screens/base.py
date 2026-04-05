"""
Base UI components and mixins for Liberal IP Roller.
Provides standardized notification and theme synchronization utilities.
"""

from typing import Optional
from textual.app import ComposeResult
from textual.screen import Screen, ModalScreen


class UIHelperMixin:
    """
    Mixin providing standardized notification methods for UI consistency.
    """
    def notify_success(self, message: str) -> None:
        """ Displays an informational (success) notification. """
        self.app.notify(message, severity="information")

    def notify_error(self, message: str) -> None:
        """ Displays an error notification. """
        self.app.notify(message, severity="error")


class BaseScreen(Screen, UIHelperMixin):
    """
    Base class for all full-screen application views.
    Ensures theme synchronization and focus management.
    """
    def on_mount(self) -> None:
        """ Synchronizes theme on initial mount. """
        self._sync_theme()
        self.set_focus(None)

    def on_resume(self) -> None:
        """ Re-synchronizes theme when returning to the screen. """
        self._sync_theme()

    def _sync_theme(self) -> None:
        """ Helper to force app-wide theme application to this screen. """
        if hasattr(self.app, "apply_theme"):
            self.app.apply_theme()


class BaseModalScreen(ModalScreen, UIHelperMixin):
    """
    Base class for all modal dialogs.
    Ensures theme consistency and non-blocking lifecycle.
    """
    def on_mount(self) -> None:
        """ Synchronizes theme on initial mount. """
        if hasattr(self.app, "apply_theme"):
            self.app.apply_theme()
        self.set_focus(None)

    def on_resume(self) -> None:
        """ Re-synchronizes theme when returning to the modal. """
        if hasattr(self.app, "apply_theme"):
            self.app.apply_theme()
