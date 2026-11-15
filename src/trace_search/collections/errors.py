"""Failures shared by the application and its CLI and MCP adapters."""


class OperationError(RuntimeError):
    """An operation failed and must not be reported as successful output."""


class DocumentNotFoundError(OperationError):
    """The requested live document is absent or outside the visible corpus."""


class DocumentReadError(OperationError):
    """A visible document could not be extracted."""


class ReindexError(OperationError):
    """Some collections failed after others may have published successfully."""

    def __init__(
        self,
        completed: tuple[tuple[str, int], ...],
        failed: tuple[tuple[str, str], ...],
    ):
        self.completed = completed
        self.failed = failed
        lines = ["Reindex failed."]
        lines.extend(f"Completed {name}: {count} chunks indexed" for name, count in completed)
        lines.extend(f"Failed {name}: {reason}" for name, reason in failed)
        super().__init__("\n".join(lines))
