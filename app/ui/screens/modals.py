"""
Modal dialog screens for Liberal IP Roller.
Includes the IP management/limit resolution modal with custom event handling.
"""

from typing import List, Dict, Optional

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Button, Label
from textual.containers import Vertical, Horizontal

from .screen_base import BaseModalScreen


class IpRow(Horizontal):
    """
    Encapsulated UI component representing a single IP address row.
    Standardized OOP approach for reliable event handling.
    """
    def __init__(self, ip_id: str, address: str, is_reserved: bool = True, **kwargs) -> None:
        super().__init__(classes="ip-item-row", **kwargs)
        self.ip_id = ip_id
        self.address = address
        self.is_reserved = is_reserved

    def compose(self) -> ComposeResult:
        """ Renders the IP address and its dedicated delete button. """
        is_reserved = getattr(self, "is_reserved", True) # Backward compat
        
        display_addr = self.address if self.address else "Internal/Locked"
        addr_text = f"{display_addr} ({self.ip_id[:8]}...)"
        if not is_reserved:
            addr_text += " [LOCKED: VM]"
            
        yield Label(addr_text)
        yield Button(
            self.app._t("delete_btn"),
            variant="error",
            id="btn-delete",
            disabled=not is_reserved
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """ 
        Catches the click locally and bubbles up a typed request. 
        Highly reliable OOP signaling.
        """
        if event.button.id == "btn-delete":
            self.post_message(IpLimitModal.IpDeleteRequested(self.ip_id))


class IpLimitModal(BaseModalScreen):
    """
    Modal dialog shown when the IP quota is reached or for manual management.
    Allows users to select specific IPs for deletion or clear all.
    """

    class IpDeleteRequested(Message):
        """
        Custom message to ensure reliable click capture in complex TUI layouts.
        """
        def __init__(self, ip_id: str) -> None:
            super().__init__()
            self.ip_id = ip_id

    def __init__(
        self,
        addresses: List[Dict],
        title_key: str = "limit_reached",
        subtitle_key: str = "select_to_delete",
        current_count: int = 0,
        ip_limit: int = 0,
        **kwargs
    ):
        """
        Initializes the modal with a list of active IP addresses.
        
        Args:
            addresses: List of address dicts to display.
            title_key: i18n key for the modal title.
            subtitle_key: i18n key for the subtitle.
            current_count: Current number of active IPs/VMs (for dynamic title).
            ip_limit: Maximum allowed IPs/VMs (for dynamic title).
        """
        super().__init__(**kwargs)
        self.addresses = addresses
        self.title_key = title_key
        self.subtitle_key = subtitle_key
        self.current_count = current_count
        self.ip_limit = ip_limit

    def compose(self) -> ComposeResult:
        """Renders the modal layout with a list of deletable IPs."""
        with Vertical(classes="modal-dialog"):
            # Use dynamic title if current/limit counts are provided
            if self.current_count and self.ip_limit:
                title_text = self.app._t(
                    "limit_reached_dynamic",
                    current=self.current_count,
                    limit=self.ip_limit
                )
            else:
                title_text = self.app._t(self.title_key)

            yield Label(title_text, classes="title")
            yield Label(self.app._t(self.subtitle_key), classes="subtitle")

            with Vertical(id="ip-list-container"):
                for addr in self.addresses:
                    yield IpRow(
                        ip_id=addr["id"], 
                        address=addr["address"],
                        is_reserved=addr.get("reserved", True)
                    )

            with Horizontal(classes="action-row-modal"):
                yield Button(
                    self.app._t("delete_all"),
                    id="btn-delete-all",
                    variant="error"
                )
                yield Button(
                    self.app._t("cancel"),
                    id="btn-cancel",
                    variant="primary"
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """ Handles standard modal actions. """
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-delete-all":
            self.dismiss("all")

    def on_ip_limit_modal_ip_delete_requested(self, message: IpDeleteRequested) -> None:
        """
        Handles the custom deletion signal from the IpRow component.
        """
        self.dismiss(message.ip_id)


class ConfirmationModal(BaseModalScreen):
    """
    Generic confirmation dialog for binary choices.
    """
    def __init__(
        self,
        title_key: str,
        subtitle_key: Optional[str] = None,
        subtitle_text: Optional[str] = None,
        confirm_key: str = "confirm",
        cancel_key: str = "cancel",
        **kwargs
    ):
        super().__init__(**kwargs)
        self.title_key = title_key
        self.subtitle_key = subtitle_key
        self.subtitle_text = subtitle_text
        self.confirm_key = confirm_key
        self.cancel_key = cancel_key

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog confirmation-modal"):
            yield Label(self.app._t(self.title_key), classes="title")
            
            # Use raw text if provided, otherwise translation key
            sub_text = self.subtitle_text if self.subtitle_text else self.app._t(self.subtitle_key)
            yield Label(sub_text, classes="subtitle")
            
            with Horizontal(classes="action-row-modal"):
                yield Button(self.app._t(self.confirm_key), id="btn-confirm", variant="primary")
                yield Button(self.app._t(self.cancel_key), id="btn-cancel", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)
