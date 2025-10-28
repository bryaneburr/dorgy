"""Test helper embedding function for deterministic Chromadb vectors."""

from __future__ import annotations

from typing import Dict, Iterable, List

from chromadb.api.types import EmbeddingFunction


class SimpleEmbeddingFunction(EmbeddingFunction[Iterable[str]]):
    """Minimal embedding function returning deterministic vectors."""

    def __init__(self) -> None:  # pragma: no cover - config hook
        self._config: dict[str, str] = {}

    @staticmethod
    def name() -> str:
        return "tests.fake_embeddings.simple_embedding_function"

    def __call__(self, input: Iterable[str] | str) -> List[List[float]]:
        if isinstance(input, str):
            texts = [input]
        else:
            texts = list(input)
        embeddings: list[list[float]] = []
        for index, text in enumerate(texts):
            length = float(len(text) % 997) / 997.0
            embeddings.append(
                [
                    length,
                    float((index + 1) % 11) / 11.0,
                    1.0 - length,
                ]
            )
        return embeddings

    def default_space(self) -> str:  # pragma: no cover - interface hook
        return "cosine"

    def supported_spaces(self) -> list[str]:  # pragma: no cover - interface hook
        return ["cosine", "l2"]

    @staticmethod
    def build_from_config(config: Dict[str, str]) -> "SimpleEmbeddingFunction":
        instance = SimpleEmbeddingFunction()
        instance._config = dict(config)
        return instance

    def get_config(self) -> Dict[str, str]:  # pragma: no cover - interface hook
        return dict(self._config)


simple_embedding_function = SimpleEmbeddingFunction()

__all__ = ["simple_embedding_function", "SimpleEmbeddingFunction"]
