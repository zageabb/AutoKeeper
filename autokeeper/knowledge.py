"""User-editable Markdown knowledge and safe Markdown rendering.

Markdown is source text, not trusted HTML or executable commands.
Stored outside Git alongside the SQLite database; updates use optimistic revision.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import bleach
from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

MAX_KNOWLEDGE_BYTES = 128 * 1024
MAX_PREVIEW_CHARS = 128 * 1024
MAX_PROMPT_CHARS = 16000
SEED = Path(__file__).with_name("default_knowledge.md")

ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "del", "div",
    "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i",
    "img", "input", "kbd", "li", "ol", "p", "pre", "section", "s",
    "span", "strong", "sub", "sup", "table", "tbody", "td", "th",
    "thead", "tr", "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title"],
    "input": ["type", "checked", "disabled"],
    "th": ["align"],
    "td": ["align"],
    "code": ["class"],
    "span": ["class"],
    "section": ["class"],
}
# Remote image loading may reveal the viewer's IP to the remote host.
# Do not allow script: or data: schemes in links or image sources.
RENDERER = (
    MarkdownIt("commonmark", {"html": False, "linkify": True})
    .enable(["table", "strikethrough", "linkify"])
    .use(tasklists_plugin)
    .use(footnote_plugin)
)


def markdown_html(source: str) -> str:
    if len(source) > MAX_PREVIEW_CHARS:
        raise ValueError("Markdown exceeds the preview size limit.")
    raw = RENDERER.render(source)
    return bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=["http", "https", "mailto"],
        strip=True,
    )


def knowledge_path(db_path: str) -> Path:
    configured = os.getenv("AUTOKEEPER_KNOWLEDGE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(db_path).parent / "knowledge.md"


def ensure_knowledge(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # Exclusive creation avoids clobbering a document from another process.
        try:
            with path.open("x", encoding="utf-8") as target:
                target.write(SEED.read_text(encoding="utf-8"))
            os.chmod(path, 0o600)
        except FileExistsError:
            pass


def revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_knowledge(path: Path) -> dict:
    ensure_knowledge(path)
    raw = path.read_bytes()
    if len(raw) > MAX_KNOWLEDGE_BYTES:
        raise ValueError("Knowledge document exceeds 128 KiB.")
    text = raw.decode("utf-8")
    return {"content": text, "revision": revision(text)}


def save_knowledge(path: Path, text: str, expected_revision: str) -> dict:
    if len(text.encode("utf-8")) > MAX_KNOWLEDGE_BYTES:
        raise ValueError("Knowledge document cannot exceed 128 KiB.")
    current = read_knowledge(path)
    if current["revision"] != expected_revision:
        raise FileExistsError("Knowledge was updated in another session. Reload before saving.")
    # File is on the same filesystem: atomic replace prevents torn writes.
    fd, name = tempfile.mkstemp(prefix=".knowledge-", suffix=".md", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(text)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return {"content": text, "revision": revision(text)}


def prompt_knowledge(path: Path) -> str:
    contents = read_knowledge(path)["content"]
    if len(contents) > MAX_PROMPT_CHARS:
        return contents[:MAX_PROMPT_CHARS] + "\n[Knowledge truncated for context length]"
    return contents
