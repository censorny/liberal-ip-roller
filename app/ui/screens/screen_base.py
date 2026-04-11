"""Shared base classes for full-screen views and modals."""

from textual.screen import Screen, ModalScreen


class UIHelperMixin:
    """Small notification helpers shared by screens and modals."""

    def notify_success(self, message: str) -> None:
        self.app.notify(message, severity="information")

    def notify_error(self, message: str) -> None:
        self.app.notify(message, severity="error")


class BaseScreen(Screen, UIHelperMixin):
    def on_mount(self) -> None:
        self.set_focus(None)


class BaseModalScreen(ModalScreen, UIHelperMixin):
    def on_mount(self) -> None:
        self.set_focus(None)
