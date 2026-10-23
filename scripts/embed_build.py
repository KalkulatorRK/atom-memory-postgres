"""Текст для эмбеддинга атома и политика проектов."""
from __future__ import annotations

import os
import re

from embeddings import content_hash


def build_embed_text(atom: dict, source_title: str = "") -> tuple[str | None, str | None]:
    """Возвращает (embed_text, skip_reason)."""
    content = (atom.get("content") or "").strip()
    meta = atom.get("metadata") or {}
    atype = atom.get("atom_type") or "text"

    if atype == "image":
        if re.match(r"^\[изображение:", content):
            cap = meta.get("caption") or meta.get("title")
            if not cap:
                return None, "image_no_caption"
            content = cap
        elif not content:
            return None, "image_no_caption"

    parts = []
    if source_title:
        parts.append(source_title.strip())
    section = meta.get("section_path")
    if section:
        if isinstance(section, list):
            parts.append(" / ".join(str(x) for x in section))
        else:
            parts.append(str(section))
    caption = meta.get("title") or meta.get("caption")
    if caption:
        parts.append(str(caption).strip())
    parts.append(content)
    text = "\n".join(p for p in parts if p)
    if not text.strip():
        return None, "empty"
    return text, None


def compute_content_hash(space: str, dims: int, embed_text: str) -> str:
    return content_hash(space, dims, embed_text)


def project_allows_cloud(policy: str) -> bool:
    return policy in ("inherit", "cloud")


def project_allows_any_embed(policy: str) -> bool:
    return policy != "none"


def cloud_denied_projects() -> set[str]:
    raw = os.environ.get("EMBED_CLOUD_DENY_PROJECTS", "")
    if not raw.strip():
        return set()
    return {x.strip() for x in raw.split(",") if x.strip()}


def effective_embed_policy(project_name: str, policy: str) -> str:
    if project_name in cloud_denied_projects():
        if policy == "inherit":
            return "local_only"
    return policy


def should_skip_embed_for_policy(policy: str, provider_kind: str) -> bool:
    if policy == "none":
        return True
    if policy == "local_only" and provider_kind == "cloud":
        return True
    return False
