"""Lossless svn:externals editing and repository-relative URL resolution.

Unrecognised lines remain available verbatim in the text editor.  In particular,
we never guess at syntax we cannot safely translate to the modern URL-first form.
"""

from dataclasses import dataclass
import posixpath
import re
import shlex
from urllib.parse import urlsplit, urlunsplit


REVISION = re.compile(r"(?:[0-9]+|HEAD)\Z", re.IGNORECASE)


def revision(value):
    value = value.strip()
    if value and not REVISION.fullmatch(value):
        raise ValueError("Use a revision number, HEAD, or leave the revision empty.")
    return value.upper()


def is_url(value):
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value)) or value.startswith(
        ("^/", "../", "//", "/")
    )


def split_peg(value):
    # An @ in svn+ssh://user@host is part of the authority, not a peg.
    boundary = value.find("/", value.find("://") + 3) if "://" in value else 0
    index = value.rfind("@")
    if index >= max(boundary, 0) and boundary != -1:
        return value[:index], revision(value[index + 1:])
    return value, ""


def quote(value):
    if any(c in value for c in "\r\n\x00"):
        raise ValueError("External fields must be on a single line.")
    if any(c.isspace() or c in "\\\"'" for c in value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


@dataclass(frozen=True)
class External:
    local_path: str
    url: str
    peg: str = ""
    operative: str = ""

    def serialize(self):
        local = self.local_path.strip()
        url = self.url.strip()
        if not local or local.startswith(("/", "-")) or re.match(r"^[A-Za-z]:", local):
            raise ValueError("Enter a relative local path for the external.")
        if any(part == ".." for part in local.replace("\\", "/").split("/")) or posixpath.normpath(local) == ".":
            raise ValueError("The local path must stay below the property directory.")
        if not is_url(url):
            raise ValueError("Enter an absolute SVN URL or a relative URL (^/, ../, //, /).")
        peg, operative = revision(self.peg), revision(self.operative)
        # Escape literal @ signs even when no peg was requested.
        suffix = "@" + peg if peg or "@" in url else ""
        prefix = "-r%s " % operative if operative else ""
        return prefix + quote(url + suffix) + " " + quote(local)


def parse_line(line):
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    tokens = shlex.split(line, comments=False, posix=True)
    operative = ""
    legacy = not is_url(tokens[0]) and not tokens[0].startswith("-r")
    index = 1 if legacy else 0
    if len(tokens) > index and tokens[index].startswith("-r"):
        flag = tokens.pop(index)
        operative = revision(tokens.pop(index) if flag == "-r" else flag[2:])
        if not operative:
            raise ValueError("Missing operative revision.")
    if len(tokens) != 2:
        raise ValueError("Expected a URL and a local path.")
    if legacy:
        local, url = tokens
        if "://" not in url:
            raise ValueError("Legacy externals require an absolute URL.")
        # In the old local-path-first format -r sets BOTH revisions and @ is literal.
        peg = operative
    else:
        url, local = tokens
        url, peg = split_peg(url)
    item = External(local, url, peg, operative)
    item.serialize()
    return item


class ExternalsDocument:
    def __init__(self, text=""):
        self.lines = text.splitlines(keepends=True)

    def entries(self):
        for index, line in enumerate(self.lines):
            try:
                item = parse_line(line)
                error = ""
            except (ValueError, IndexError) as exc:
                item, error = None, str(exc)
            if item is not None or error:
                yield index, item, error

    def replace(self, index, item):
        old = self.lines[index]
        ending = "\r\n" if old.endswith("\r\n") else "\n" if old.endswith("\n") else ""
        self.lines[index] = item.serialize() + ending

    def append(self, item):
        line = item.serialize()
        if self.lines and not self.lines[-1].endswith(("\n", "\r")):
            self.lines[-1] += "\n"
        self.lines.append(line + "\n")

    def text(self):
        return "".join(self.lines)


def resolve_url(url, owner_url, root_url):
    """Resolve against the directory carrying the property, never the WC root."""
    if "://" in url:
        return url
    owner = urlsplit(owner_url)
    root = urlsplit(root_url)
    if not owner.scheme:
        raise ValueError("Cannot determine the URL of the property directory.")
    if url.startswith("^/"):
        if not root.scheme:
            raise ValueError("Cannot determine the repository root URL.")
        parts = root
        path = root.path.rstrip("/") + "/" + url[2:]
    elif url.startswith("//"):
        return owner.scheme + ":" + url
    elif url.startswith("/"):
        parts, path = owner, url
    elif url.startswith("../"):
        parts, path = owner, owner.path.rstrip("/") + "/" + url
    else:
        raise ValueError("Unsupported relative external URL.")
    return urlunsplit((parts.scheme, parts.netloc, posixpath.normpath(path), "", ""))
