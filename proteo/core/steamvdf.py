"""Minimal reader/writer for Steam's text VDF (KeyValues) files, plus the rule
for injecting proteo's launch wrapper into a game's launch options.

Why parse at all: `localconfig.vdf` is the only place Steam keeps per-game
launch options, and setting them for every installed game by hand is the chore
this avoids. Why a real parser rather than a regex: launch options for one app
have to be edited while every other key in a file of thousands survives
untouched, and a regex over nested KeyValues is exactly how a config file gets
quietly corrupted.

The document is kept as nested lists of `(key, value)` pairs rather than dicts:
KeyValues allows repeated keys and Steam cares about order, and neither
survives a dict round-trip.
"""

from __future__ import annotations

Node = list[tuple[str, "str | Node"]]

WRAPPER = "proteo profile --"
COMMAND = "%command%"


class VdfError(ValueError):
    pass


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def _unescape(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace('"', '\\"')
                .replace("\n", "\\n").replace("\t", "\\t"))


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        elif c in "{}":
            tokens.append(("brace", c))
            i += 1
        elif c == '"':
            i += 1
            start = i
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
            if i >= n:
                raise VdfError("unterminated quoted string")
            tokens.append(("string", _unescape(text[start:i])))
            i += 1
        else:  # unquoted token, rare but legal
            start = i
            while i < n and text[i] not in ' \t\r\n"{}':
                i += 1
            tokens.append(("string", text[start:i]))
    return tokens


def loads(text: str) -> Node:
    tokens = _tokenize(text)
    pos = 0

    def parse_block(depth: int) -> Node:
        nonlocal pos
        node: Node = []
        while pos < len(tokens):
            kind, value = tokens[pos]
            if kind == "brace":
                if value == "}":
                    if depth == 0:
                        raise VdfError("unbalanced closing brace")
                    pos += 1
                    return node
                raise VdfError("unexpected opening brace where a key was due")
            pos += 1
            if pos >= len(tokens):
                raise VdfError(f"key {value!r} has no value")
            nkind, nvalue = tokens[pos]
            if nkind == "brace" and nvalue == "{":
                pos += 1
                node.append((value, parse_block(depth + 1)))
            elif nkind == "string":
                pos += 1
                node.append((value, nvalue))
            else:
                raise VdfError(f"key {value!r} is followed by {nvalue!r}")
        if depth != 0:
            raise VdfError("unbalanced opening brace")
        return node

    return parse_block(0)


# --------------------------------------------------------------------------
# serialising — Steam's own style: tab indent, two tabs between key and value
# --------------------------------------------------------------------------

def dumps(node: Node, depth: int = 0) -> str:
    pad = "\t" * depth
    lines = []
    for key, value in node:
        if isinstance(value, str):
            lines.append(f'{pad}"{_escape(key)}"\t\t"{_escape(value)}"')
        else:
            lines.append(f'{pad}"{_escape(key)}"')
            lines.append(f"{pad}{{")
            inner = dumps(value, depth + 1)
            if inner:
                lines.append(inner)
            lines.append(f"{pad}}}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# navigating
# --------------------------------------------------------------------------

def find(node: Node, *path: str) -> Node | str | None:
    """Follow a key path, matching case-insensitively — Steam has shipped both
    `Steam` and `steam` for the same key across client versions."""
    current: Node | str | None = node
    for key in path:
        if not isinstance(current, list):
            return None
        wanted = key.lower()
        current = next((v for k, v in current if k.lower() == wanted), None)
    return current


def set_value(node: Node, key: str, value: str) -> None:
    """Set a leaf, replacing the existing entry in place to preserve order."""
    wanted = key.lower()
    for index, (existing, _) in enumerate(node):
        if existing.lower() == wanted:
            node[index] = (existing, value)
            return
    node.append((key, value))


# --------------------------------------------------------------------------
# the launch-options rule
# --------------------------------------------------------------------------

def with_wrapper(options: str, wrapper: str = WRAPPER) -> str:
    """Add proteo's wrapper to one game's launch options, keeping what is there.

    `%command%` is where Steam substitutes the real command line, so the wrapper
    goes immediately before it — never at the front, which would swallow any
    environment assignment the user put there (`WINEDLLOVERRIDES=... %command%`
    would become an argument to proteo instead of an env var for the game).
    """
    options = options.strip()
    if wrapper in options:
        return options
    if not options:
        return f"{wrapper} {COMMAND}"
    if COMMAND in options:
        return options.replace(COMMAND, f"{wrapper} {COMMAND}", 1)
    # no %command%: Steam appends these as arguments to the game, so they have
    # to stay after it
    return f"{wrapper} {COMMAND} {options}"


def without_wrapper(options: str, wrapper: str = WRAPPER) -> str:
    """Undo `with_wrapper`, leaving unrelated options exactly as they were."""
    if wrapper not in options:
        return options.strip()
    stripped = options.replace(f"{wrapper} {COMMAND}", COMMAND, 1)
    stripped = stripped.replace(wrapper, "", 1)
    stripped = " ".join(stripped.split())
    # a bare "%command%" is what Steam stores as "no options at all"
    return "" if stripped == COMMAND else stripped
