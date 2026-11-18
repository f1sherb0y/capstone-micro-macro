"""Lightweight local keyword retriever.

This is intentionally small and optional. It gives CAMEL prompts policy,
methodology, or local-doc snippets without making vector databases or CAMEL
retrievers a hard runtime dependency.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DOCUMENTS = [
    PROJECT_ROOT / "reports" / "methodology_batch001.md",
    PROJECT_ROOT / "reports" / "source_registry_batch001.md",
    PROJECT_ROOT / "reports" / "validation_report_batch001.md",
    *sorted((PROJECT_ROOT / "camel_ai_docs" / "key_modules").glob("*.md")),
]

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")
PARAGRAPH_PATTERN = re.compile(r"\n\s*\n")


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text) if len(token) > 1}


class EnterpriseRetriever:
    def __init__(self, documents: list[Path] | None = None) -> None:
        self.documents = documents or DEFAULT_DOCUMENTS
        self._index: list[dict[str, Any]] | None = None

    def _build_index(self) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for path in self.documents:
            if not path.exists() or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            paragraphs = [part.strip() for part in PARAGRAPH_PATTERN.split(text) if part.strip()]
            for index, paragraph in enumerate(paragraphs):
                tokens = _tokens(paragraph)
                if not tokens:
                    continue
                chunks.append(
                    {
                        "path": str(path.relative_to(PROJECT_ROOT)),
                        "chunk": index,
                        "tokens": tokens,
                        "snippet": paragraph[:800],
                    }
                )
        return chunks

    def _get_index(self) -> list[dict[str, Any]]:
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        matches: list[dict[str, Any]] = []
        for item in self._get_index():
            overlap = query_tokens & item["tokens"]
            if not overlap:
                continue
            score = len(overlap) / max(len(query_tokens), 1)
            matches.append(
                {
                    "path": item["path"],
                    "chunk": item["chunk"],
                    "score": round(score, 4),
                    "snippet": item["snippet"],
                }
            )
        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[:limit]


enterprise_retriever = EnterpriseRetriever()
