"""
Base UI components and mixins for Liberal IP Roller.
Provides standardized notification utilities.
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
    Ensures focus management.
    """
    def on_mount(self) -> None:
        """ Focus management on initial mount. """
        self.set_focus(None)

    def on_resume(self) -> None:
        """ Focus management when returning. """
        pass


class BaseModalScreen(ModalScreen, UIHelperMixin):
    """
    Base class for all modal dialogs.
    Ensures non-blocking lifecycle.
    """
    def on_mount(self) -> None:
        """ Focus management on initial mount. """
        self.set_focus(None)

    def on_resume(self) -> None:
        """ Non-blocking return. """
        pass
