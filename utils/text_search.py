def matches_all_words(term: str, *fields) -> bool:
    """
    True if every whitespace-separated word in term appears as a
    case-insensitive substring in at least one of fields.

    Mirrors models.product.search()'s matching semantics (multi-word AND,
    OR across columns) for screens that filter an already-loaded list
    client-side instead of re-querying the database per keystroke.

    e.g. matches_all_words("oasis dip", "OASIS BEETROOT DIP") is True;
    matches_all_words("oasis dip", "OASIS BEETROOT DIP", "") is also True
    if either word could come from either field.
    """
    words = [w for w in term.strip().lower().split() if w]
    if not words:
        return True
    haystacks = [(f or '').lower() for f in fields]
    return all(any(word in h for h in haystacks) for word in words)
