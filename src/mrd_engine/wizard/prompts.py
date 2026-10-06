"""
Prompt helpers for the wizard. Thin wrappers around rich.prompt that add
back-navigation, default handling, and consistent styling.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax

console = Console()


def menu(title: str, options: list[tuple[str, str]], default: str | None = None) -> str:
    """
    Render a numbered menu and return the selected key.
    options = [("1", "Continue with existing"), ("2", "Add tables"), ...]
    """
    console.print()
    console.rule(f"[bold]{title}[/bold]")
    for key, label in options:
        console.print(f"  [bold cyan]\\[{key}][/bold cyan]  {label}")
    keys = [k for k, _ in options]
    return Prompt.ask("\nChoose", choices=keys, default=default or keys[0])


def yesno(prompt: str, default: bool = True) -> bool:
    return Confirm.ask(prompt, default=default)


def text(prompt: str, default: str | None = None, allow_empty: bool = False) -> str:
    while True:
        v = Prompt.ask(prompt, default=default or "")
        if v or allow_empty:
            return v
        console.print("[yellow]empty input — please type a value.[/yellow]")


def choice(prompt: str, options: list[str], default: str | None = None) -> str:
    return Prompt.ask(prompt, choices=options, default=default or options[0])


def multi_pick(prompt: str, max_index: int) -> list[int]:
    """
    Accept indices like "0 2 4", "all", "none", or ranges "0-3,5".
    Returns sorted unique list of valid indices.
    """
    raw = Prompt.ask(prompt, default="none").strip().lower()
    if raw in {"", "none", "skip", "skip-all"}:
        return []
    if raw in {"all", "accept-all"}:
        return list(range(max_index))
    picked: set[int] = set()
    for chunk in raw.replace(",", " ").split():
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            try:
                for i in range(int(lo), int(hi) + 1):
                    if 0 <= i < max_index:
                        picked.add(i)
            except ValueError:
                continue
        else:
            try:
                i = int(chunk)
                if 0 <= i < max_index:
                    picked.add(i)
            except ValueError:
                continue
    return sorted(picked)


def confirm_destructive(reason: str, magic_word: str = "RESET") -> bool:
    """Require user to type a literal magic word. Soft-Y is not enough."""
    console.print()
    console.print(f"[bold red]DESTRUCTIVE ACTION:[/bold red] {reason}")
    typed = Prompt.ask(f"Type [bold]{magic_word}[/bold] to confirm (anything else aborts)")
    return typed.strip() == magic_word


def open_in_editor(path: Path) -> None:
    """Open path in $EDITOR (or notepad/nano fallback). Blocks until editor exits."""
    editor = os.environ.get("EDITOR")
    if not editor:
        editor = "notepad" if sys.platform == "win32" else "nano"
    console.print(f"[dim]opening {path} in {editor}...[/dim]")
    try:
        subprocess.run([editor, str(path)], check=False)
    except FileNotFoundError:
        console.print(f"[red]{editor} not found — open {path} manually, then press Enter.[/red]")
        input("press Enter when done > ")


def render_yaml(text_block: str, title: str | None = None) -> None:
    if title:
        console.rule(title)
    console.print(Syntax(text_block, "yaml", line_numbers=False, word_wrap=True))


def info(msg: str) -> None:
    console.print(f"[cyan]i[/cyan] {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow]![/yellow] {msg}")


def err(msg: str) -> None:
    console.print(f"[red]x[/red] {msg}")


def ok(msg: str) -> None:
    console.print(f"[green]+[/green] {msg}")


def rule(label: str) -> None:
    console.rule(f"[bold]{label}[/bold]")
