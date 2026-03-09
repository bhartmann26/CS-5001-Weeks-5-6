"""
Console — ANSI-colored terminal output.
No external dependencies. Degrades gracefully on non-TTY.
"""

import sys
import os
import textwrap

_IS_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    if not _IS_TTY:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t):    return _c("1", t)
def dim(t):     return _c("2", t)
def green(t):   return _c("32", t)
def yellow(t):  return _c("33", t)
def red(t):     return _c("31", t)
def blue(t):    return _c("34", t)
def cyan(t):    return _c("36", t)
def magenta(t): return _c("35", t)
def white(t):   return _c("37", t)

TERM_WIDTH = min(os.get_terminal_size().columns if _IS_TTY else 88, 100)


class Console:

    @staticmethod
    def header(title: str):
        print()
        line = "─" * TERM_WIDTH
        print(cyan(line))
        print(bold(cyan(f"  🤖  {title}")))
        print(cyan(line))
        print()

    @staticmethod
    def section(title: str):
        print()
        print(bold(blue(f"▶ {title}")))
        print(dim("─" * min(len(title) + 4, TERM_WIDTH)))

    @staticmethod
    def info(msg: str):
        print(f"  {dim('·')} {msg}")

    @staticmethod
    def success(msg: str):
        print(f"  {green('✓')} {green(msg)}")

    @staticmethod
    def warning(msg: str):
        print(f"  {yellow('⚠')} {yellow(msg)}", file=sys.stderr)

    @staticmethod
    def error(msg: str):
        print(f"  {red('✗')} {red(msg)}", file=sys.stderr)

    @staticmethod
    def step(n: int, total: int, msg: str):
        prefix = cyan(f"[{n}/{total}]")
        print(f"  {prefix} {msg}")

    @staticmethod
    def kv(key: str, value: str, indent: int = 2):
        k = bold(f"{key}:")
        pad = " " * indent
        print(f"{pad}{k} {value}")

    @staticmethod
    def badge(label: str, value: str, color_fn=None):
        if color_fn is None:
            color_fn = white
        k = dim(f"[{label}]")
        v = color_fn(value)
        print(f"  {k} {v}")

    @staticmethod
    def divider(char: str = "─"):
        print(dim(char * TERM_WIDTH))

    @staticmethod
    def blank():
        print()

    @staticmethod
    def text_block(text: str, indent: int = 4, max_width: int = None):
        w = max_width or (TERM_WIDTH - indent)
        prefix = " " * indent
        for line in text.splitlines():
            if not line.strip():
                print()
                continue
            for wrapped in textwrap.wrap(line, w) or [""]:
                print(f"{prefix}{wrapped}")

    @staticmethod
    def code_block(text: str, lang: str = ""):
        fence = dim("```" + lang)
        print(f"  {fence}")
        for line in text.splitlines():
            print(f"    {dim(line)}")
        print(f"  {dim('```')}")

    @staticmethod
    def diff_preview(diff: str, max_lines: int = 30):
        lines = diff.splitlines()[:max_lines]
        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                print(f"  {green(line)}")
            elif line.startswith("-") and not line.startswith("---"):
                print(f"  {red(line)}")
            elif line.startswith("@@"):
                print(f"  {cyan(line)}")
            else:
                print(f"  {dim(line)}")
        if len(diff.splitlines()) > max_lines:
            remaining = len(diff.splitlines()) - max_lines
            print(dim(f"  … {remaining} more lines"))

    @staticmethod
    def risk_badge(risk: str) -> str:
        colors = {"low": green, "medium": yellow, "high": red}
        fn = colors.get(risk.lower(), white)
        icons = {"low": "●", "medium": "◆", "high": "▲"}
        icon = icons.get(risk.lower(), "•")
        return fn(f"{icon} {risk.upper()}")

    @staticmethod
    def category_badge(category: str) -> str:
        colors = {
            "feature": cyan, "bugfix": red, "refactor": blue,
            "docs": green, "test": yellow, "chore": dim,
            "security": magenta, "performance": yellow,
        }
        fn = colors.get(category.lower(), white)
        return fn(f"[{category.upper()}]")

    @staticmethod
    def prompt(question: str, default: str = "") -> str:
        hint = f" [{default}]" if default else ""
        try:
            answer = input(f"\n  {bold('?')} {question}{hint}: ").strip()
            return answer or default
        except (KeyboardInterrupt, EOFError):
            return default

    @staticmethod
    def confirm(question: str, default: bool = False) -> bool:
        hint = "Y/n" if default else "y/N"
        try:
            answer = input(f"\n  {bold('?')} {question} [{hint}]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return False
        if not answer:
            return default
        return answer in ("y", "yes")

    @staticmethod
    def choose(question: str, options: list[str]) -> str:
        print(f"\n  {bold('?')} {question}")
        for i, opt in enumerate(options, 1):
            print(f"    {cyan(str(i))}) {opt}")
        while True:
            try:
                raw = input(f"\n  Enter number [1-{len(options)}]: ").strip()
                idx = int(raw) - 1
                if 0 <= idx < len(options):
                    return options[idx]
                print(red(f"  Please enter 1–{len(options)}"))
            except (ValueError, KeyboardInterrupt, EOFError):
                return options[0]

    @staticmethod
    def markdown_preview(text: str, max_lines: int = 50):
        """Render markdown-ish text to terminal (simple)."""
        lines = text.splitlines()[:max_lines]
        for line in lines:
            if line.startswith("# "):
                print(bold(cyan(line)))
            elif line.startswith("## "):
                print(bold(blue(line)))
            elif line.startswith("### "):
                print(bold(line))
            elif line.startswith("- ") or line.startswith("* "):
                print(f"  {cyan('•')} {line[2:]}")
            elif line.startswith("**") and line.endswith("**"):
                print(bold(line.replace("**", "")))
            elif line.startswith("> "):
                print(dim(f"  │ {line[2:]}"))
            elif line.startswith("```"):
                print(dim(line))
            else:
                print(line)
        if len(text.splitlines()) > max_lines:
            print(dim(f"  … {len(text.splitlines()) - max_lines} more lines"))

    @staticmethod
    def agent_log(role: str, msg: str, level: str = "info"):
        """Emit a tagged [Role] log line used by multi-agent pattern."""
        role_colors = {
            "Planner":    cyan,
            "Writer":     blue,
            "Critic":     yellow,
            "Gatekeeper": magenta,
            "Reviewer":   green,
        }
        level_colors = {
            "info":    dim,
            "success": green,
            "warn":    yellow,
            "error":   red,
        }
        role_fn  = role_colors.get(role, white)
        level_fn = level_colors.get(level, dim)
        tag = bold(role_fn(f"[{role}]"))
        print(f"  {tag} {level_fn(msg)}")
