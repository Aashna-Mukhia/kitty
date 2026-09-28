import json
import re
import subprocess
from gettext import gettext as _
from pathlib import Path
from subprocess import PIPE, run

from kittens.tui.handler import Handler
from kittens.tui.line_edit import LineEdit
from kittens.tui.loop import Loop
from kittens.tui.operations import (
    clear_screen,
    cursor,
    set_line_wrapping,
    set_window_title,
    styled,
)
from kitty.config import cached_values_for
from kitty.key_encoding import EventType
from kitty.typing_compat import KeyEventType, ScreenSize

NON_SPACE_PATTERN = re.compile(r"\S+")
SPACE_PATTERN = re.compile(r"\s+")
SPACE_PATTERN_END = re.compile(r"\s+$")
SPACE_PATTERN_START = re.compile(r"^\s+")

NON_ALPHANUM_PATTERN = re.compile(r"[^\w\d]+")
NON_ALPHANUM_PATTERN_END = re.compile(r"[^\w\d]+$")
NON_ALPHANUM_PATTERN_START = re.compile(r"^[^\w\d]+")
ALPHANUM_PATTERN = re.compile(r"[\w\d]+")


def call_remote_control(args: list[str]) -> None:
    subprocess.run(["kitty", "@", *args], capture_output=True)


def reindex(text: str, pattern: re.Pattern[str], right: bool = False):
    if not right:
        m = pattern.search(text)
    else:
        matches = [x for x in pattern.finditer(text) if x]
        if not matches:
            raise ValueError
        m = matches[-1]

    if not m:
        raise ValueError

    return m.span()


SCROLLMARK_FILE = Path(__file__).parent / "scroll_mark.py"


class Search(Handler):
    def __init__(self, cached_values, window_ids, error=""):
        self.cached_values = cached_values
        self.window_ids = window_ids
        self.error = error
        self.line_edit = LineEdit()

        last_search = cached_values.get("last_search", "")
        self.line_edit.add_text(last_search)
        self.text_marked = bool(last_search)

        self.mode = cached_values.get("mode", "text")
        self.update_prompt()
        self.mark()

    def update_prompt(self):
        self.prompt = "~> " if self.mode == "regex" else "=> "

    def init_terminal_state(self):
        self.write(set_line_wrapping(False))
        self.write(set_window_title(_("Search")))

    def initialize(self):
        self.init_terminal_state()
        self.draw_screen()

    def draw_screen(self):
        self.write(clear_screen())

        if self.window_ids:
            input_text = self.line_edit.current_input
            if self.text_marked:
                self.line_edit.current_input = styled(input_text, reverse=True)
            self.line_edit.write(self.write, self.prompt)
            self.line_edit.current_input = input_text

        if self.error:
            with cursor(self.write):
                self.print("")
                for l in self.error.split("\n"):
                    self.print(l)

    def refresh(self):
        self.draw_screen()
        self.mark()

    def switch_mode(self):
        self.mode = "regex" if self.mode == "text" else "text"
        self.cached_values["mode"] = self.mode
        self.update_prompt()

    def on_text(self, text, in_bracketed_paste=False):
        if self.text_marked:
            self.text_marked = False
            self.line_edit.clear()
        self.line_edit.on_text(text, in_bracketed_paste)
        self.refresh()

    def on_key(self, key_event: KeyEventType):
        if self.line_edit.on_key(key_event):
            self.refresh()
            return

        if key_event.matches("ctrl+u"):
            self.line_edit.clear()
        elif key_event.matches("tab"):
            self.switch_mode()
        elif key_event.matches("up") or key_event.matches("f3"):
            for arg in self.match_args():
                call_remote_control(["kitten", arg, str(SCROLLMARK_FILE)])
        elif key_event.matches("down") or key_event.matches("shift+f3"):
            for arg in self.match_args():
                call_remote_control(["kitten", arg, str(SCROLLMARK_FILE), "next"])
        elif key_event.matches("enter"):
            self.quit(0)
        elif key_event.matches("esc"):
            self.quit(1)

        self.refresh()

    def match_args(self):
        return [f"--match=id:{wid}" for wid in self.window_ids]

    def mark(self):
        if not self.window_ids:
            return

        text = self.line_edit.current_input
        if text:
            match_case = "i" if text.islower() else ""
            match_type = match_case + self.mode

            for arg in self.match_args():
                call_remote_control(["create-marker", arg, match_type, "1", text])
        else:
            self.remove_mark()

    def remove_mark(self):
        for arg in self.match_args():
            call_remote_control(["remove-marker", arg])

    def quit(self, return_code):
        self.cached_values["last_search"] = self.line_edit.current_input
        self.remove_mark()

        if return_code:
            for arg in self.match_args():
                call_remote_control(["scroll-window", arg, "end"])

        self.quit_loop(return_code)


def main(args):
    call_remote_control(
        ["resize-window", "--self", "--axis=vertical", "--increment", "-100"]
    )

    error = ""
    if len(args) < 2 or not args[1].isdigit():
        error = "Error: Window id must be provided."

    window_ids = [int(args[1])]

    loop = Loop()
    with cached_values_for("search") as cached_values:
        handler = Search(cached_values, window_ids, error)
        loop.loop(handler)
