"""Configuration management using pydantic-settings."""

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SUPPORTED_MODELS = {
    "all-MiniLM-L6-v2": {"dims": 384, "pooling": "mean"},
    "BAAI/bge-base-en-v1.5": {"dims": 768, "pooling": "cls"},
}
COLLECTION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_collection_name(name: str) -> str:
    """Validate a collection name before using it as a selector and path segment."""
    if not COLLECTION_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"Invalid collection name '{name}'. "
            "Use only letters, numbers, underscores, and hyphens."
        )
    return name


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Knowledge base path (required for runtime index/search operations)
    kb_path: Path | None = Field(
        default=None,
        description="Path to knowledge base (required for indexing and document access)",
    )
    index_path: Path | None = None  # Defaults to kb_path if not set
    chroma_path: Path | None = None  # Explicit ChromaDB path (optional)

    # Multi-collection mode: "name:path,name:path,..."
    kb_collections: str | None = Field(
        default=None,
        description="Comma-separated name:path pairs for multi-collection mode",
    )

    eval_golden_queries: Path | None = Field(
        default=None,
        description="Optional path to your golden queries YAML (overrides default tools/eval/golden_queries.yaml)",
    )

    # Embedding model
    embedding_model: str = "all-MiniLM-L6-v2"

    # Embedding runtime backend
    embedding_backend: Literal["torch", "onnx"] = Field(
        default="onnx",
        description="Embedding runtime: 'onnx' (fastembed int8, default) or 'torch' (SentenceTransformer)",
    )

    # BM25 parameters (tuned for short wiki chunks)
    bm25_k1: float = Field(
        default=1.2, gt=0, description="BM25 k1 (term frequency saturation)"
    )
    bm25_b: float = Field(
        default=0.5, ge=0, le=1, description="BM25 b (document length normalization)"
    )

    # Reranker settings
    reranker_enabled: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Embedding warmup (one-time pre-encode at server bootstrap)
    embedding_warmup_enabled: bool = Field(
        default=True,
        description="Pre-encode a fixed batch at startup to flatten first-query tail latency",
    )

    # Chunking settings
    use_token_based_chunking: bool = False
    enable_chunk_overlap: bool = True
    char_chunk_size: int = Field(
        default=1000, gt=0, le=10000, description="Max chars per chunk"
    )
    char_overlap_size: int = Field(
        default=100, ge=0, description="Character overlap between chunks"
    )
    token_chunk_size: int = Field(
        default=512, gt=0, le=2048, description="Max tokens per chunk"
    )
    token_overlap_size: int = Field(
        default=50, ge=0, description="Token overlap between chunks"
    )

    # Directory exclusions (comma-separated)
    exclude_patterns: str = (
        "node_modules,.venv,__pycache__,.next,.git,dbt_packages,.mcp-search"
    )

    # Logging
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @field_validator("kb_path")
    @classmethod
    def validate_kb_path(cls, v: Path | None) -> Path | None:
        if v is None:
            return None
        if not v.exists():
            raise ValueError(f"Knowledge base path does not exist: {v}")
        if not v.is_dir():
            raise ValueError(f"Knowledge base path is not a directory: {v}")
        return v

    @field_validator("embedding_model")
    @classmethod
    def validate_embedding_model(cls, v: str) -> str:
        if v not in SUPPORTED_MODELS:
            raise ValueError(
                f"Unknown embedding model: {v}. "
                f"Supported models: {list(SUPPORTED_MODELS.keys())}"
            )
        return v

    @field_validator("char_chunk_size")
    @classmethod
    def warn_large_char_chunk(cls, v: int) -> int:
        if v > 5000:
            logging.getLogger(__name__).warning(
                "char_chunk_size=%d may exceed embedding model context", v
            )
        return v

    @property
    def embedding_dims(self) -> int:
        return SUPPORTED_MODELS[self.embedding_model]["dims"]

    @property
    def embedding_pooling(self) -> str:
        return SUPPORTED_MODELS[self.embedding_model]["pooling"]

    @property
    def model_slug(self) -> str:
        """Filesystem-safe model name slug."""
        return self.embedding_model.replace("/", "_").replace("-", "_").lower()

    @property
    def exclude_patterns_list(self) -> list[str]:
        return [p.strip() for p in self.exclude_patterns.split(",") if p.strip()]

    @property
    def resolved_kb_path(self) -> Path:
        """Get KB path or raise a clear runtime error if unset."""
        if self.kb_path is None:
            raise ValueError(
                "KB_PATH is required for indexing/search operations. "
                "Set KB_PATH to a valid knowledge base directory, for example "
                "'export KB_PATH=/path/to/your/docs'."
            )
        return self.kb_path

    @property
    def parsed_collections(self) -> dict[str, Path]:
        """Parse KB_COLLECTIONS into {name: path} dict.

        Falls back to KB_PATH as a single collection named after its directory.
        Raises ValueError if both are set or neither is set.
        """
        if self.kb_collections and self.kb_path:
            raise ValueError(
                "KB_COLLECTIONS and KB_PATH are mutually exclusive — set one, not both."
            )
        if self.kb_collections:
            collections = {}
            for entry in self.kb_collections.split(","):
                entry = entry.strip()
                if ":" not in entry:
                    raise ValueError(
                        f"Invalid KB_COLLECTIONS entry '{entry}'. "
                        "Expected format: 'name:/path/to/kb'"
                    )
                name, path_str = entry.split(":", 1)
                name = name.strip()
                validate_collection_name(name)
                if name in collections:
                    raise ValueError(f"Duplicate collection name: {name}")
                path = Path(path_str.strip())
                if not path.exists():
                    raise ValueError(f"Collection '{name}' path does not exist: {path}")
                if not path.is_dir():
                    raise ValueError(
                        f"Collection '{name}' path is not a directory: {path}"
                    )
                collections[name] = path
            return collections
        elif self.kb_path:
            return {self.kb_path.name: self.kb_path}
        else:
            raise ValueError(
                "Set KB_COLLECTIONS or KB_PATH. "
                "KB_COLLECTIONS format: 'name:/path,name:/path'"
            )

    @property
    def tokenizer_model(self) -> str:
        tokenizer_map = {
            "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
        }
        return tokenizer_map.get(self.embedding_model, self.embedding_model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


class _LazySettingsProxy:
    """Lazily resolve settings on attribute access."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_settings(), name)


settings = _LazySettingsProxy()


def configure_logging() -> None:
    log_level = get_settings().log_level
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
