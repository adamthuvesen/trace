"""Compare planned targets using their destination filesystem's naming rules."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory


def validate_distinct_targets(targets: Sequence[tuple[str, Path]]) -> None:
    """Reject aliases and file/directory conflicts before creating target files."""
    groups: dict[tuple[int, int], list[tuple[str, Path, Path]]] = defaultdict(list)
    for label, destination in targets:
        ancestor = destination.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        identity = ancestor.stat()
        groups[(identity.st_dev, identity.st_ino)].append((label, destination, ancestor))

    for group in groups.values():
        if len(group) < 2:
            continue
        lexical: dict[Path, str] = {}
        for label, destination, ancestor in group:
            relative = destination.relative_to(ancestor)
            if relative in lexical:
                raise ValueError(
                    f"Destination collision: {lexical[relative]} and {label} "
                    f"both map to {destination}"
                )
            lexical[relative] = label
        # A scratch mirror detects case and Unicode aliases without creating targets.
        with TemporaryDirectory(prefix=".trace-plan-", dir=group[0][2]) as name:
            mirror = Path(name)
            claimed: dict[tuple[int, int], str] = {}
            for label, destination, ancestor in group:
                probe = mirror / destination.relative_to(ancestor)
                try:
                    probe.parent.mkdir(parents=True, exist_ok=True)
                except (FileExistsError, NotADirectoryError) as error:
                    raise ValueError(
                        f"Destination file conflicts with a directory: {destination}"
                    ) from error
                if probe.exists():
                    if probe.is_dir():
                        raise ValueError(
                            f"Destination file conflicts with a directory: {destination}"
                        )
                    identity = probe.stat()
                    previous = claimed[(identity.st_dev, identity.st_ino)]
                    raise ValueError(
                        f"Destination collision: {previous} and {label} "
                        f"both map to {destination} on this filesystem"
                    )
                with probe.open("xb"):
                    pass
                identity = probe.stat()
                claimed[(identity.st_dev, identity.st_ino)] = label
