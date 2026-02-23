def normalize_name(name: str) -> str:
    """Lowercase + strip for DB comparison."""
    if not name:
        return ""
    return " ".join(name.strip().split()).lower()


def title_case(name: str) -> str:
    """Convert to Title Case for display."""
    if not name:
        return ""
    return name.strip().title()
