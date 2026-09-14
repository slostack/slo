"""Clickable authorization link shared by browser and device authorization presentations."""

from __future__ import annotations

from textual.content import Content
from textual.style import Style
from textual.widgets import Link

from config.logger import log_info

__all__ = ["AuthorizationLink"]


class AuthorizationLink(Link):
    """Paint one authorization URL as a terminal hyperlink that also opens when clicked.

    Reuses Textual's ``Link`` (click and Enter already call ``action_open_link``) and
    adds only two things: the painted text carries a hyperlink style, so terminals emit
    OSC 8 for Cmd/Ctrl-click, and opening is best effort, so a missing browser never
    breaks the modal or hides the URL.
    """

    # Link defaults to ``width: auto``, which keeps a long no-whitespace URL on one
    # clipped row. Wrap inside the available width wherever this widget is mounted.
    DEFAULT_CSS = """
    AuthorizationLink {
        width: 1fr;
        height: auto;
        text-wrap: wrap;
        overflow-x: hidden;
    }
    """

    def show(self, *, url: str) -> None:
        """Display the full URL as literal, wrapped, hyperlink-styled text and target it on click.

        WHAT: Sets the click target and renders the URL without markup parsing, so ``[`` and
            ``]`` stay literal and every painted segment links to the exact URL.
        WHO: OAuthStatusWidget calls this for the browser authorization URL and the device
            verification URL.
        WHEN: Once per presentation, after the flow publishes its instructions.

        Args:
            url (str): Authorization or verification URL; never logged.
        """
        self.url = url
        self.update(Content.styled(text=url, style=Style(link=url)))

    def action_open_link(self) -> None:
        """Ask the app to open the URL in a browser, swallowing any launch failure.

        WHO: Textual's ``Link.on_click`` and the inherited Enter binding call this action.
        WHEN: Whenever the user clicks or activates the link; before a presentation arrives
            the URL is empty and nothing happens.
        """
        if not self.url:
            return
        try:
            self.app.open_url(self.url)
        except Exception:
            log_info(msg="AuthorizationLink could not open a browser; the URL remains visible")
