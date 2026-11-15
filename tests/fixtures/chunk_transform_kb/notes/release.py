"""Release helpers with no Markdown headings."""


def next_version(current: str, part: str) -> str:
    """Return the next version string for a patch, minor, or major release."""
    major, minor, patch = (int(piece) for piece in current.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def tag_name(version: str) -> str:
    """Prefix the version so release tags sort apart from other tags."""
    return f"v{version}"
