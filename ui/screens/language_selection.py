"""
Initial Language Selection Screen for Liberal IP Roller.
Allows the user to pick between English and Russian on first launch.
"""

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Label
from textual.containers import Vertical, Center

from ui.widgets import CustomHeader
from .base import BaseScreen


class LanguageSelection(BaseScreen):
    """
    Onboarding screen for selecting the application language.
    Appears only if 'skip_language_selection' is False in config.
    """

    def compose(self) -> ComposeResult:
        """ Renders the welcome box with language options. """
        yield CustomHeader()
        with Center():
            with Vertical(id="service-selection-box"):
                yield Label("Welcome / Добро пожаловать", classes="title")
                yield Label(
                    "Select your language / Выберите язык", 
                    classes="subtitle"
                )
                yield Button("English", id="lang-en", variant="primary")
                yield Button("Русский", id="lang-ru", variant="primary")
                yield Button("Exit / Выход", id="btn-exit")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """ Handles language selection and persistence. """
        btn_id = event.button.id
        if not btn_id:
            return

        if btn_id == "lang-en":
            self.set_language("en")
        elif btn_id == "lang-ru":
            self.set_language("ru")
        elif btn_id == "btn-exit":
            self.app.exit()

    def set_language(self, lang: str) -> None:
        """
        Updates the global configuration and navigates to service selection.
        """
        config = self.app.config_provider.config
        config.language = lang
        self.app.config_provider.save()

        # Update runtime i18n state
        self.app.i18n.language = lang
        self.app.title = self.app._t("app_title")

        # Routing to next onboarding step
        self.app.switch_screen("service_selection")
