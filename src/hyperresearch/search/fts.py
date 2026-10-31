"""FTS5 full-text search engine."""

from __future__ import annotations

import json
import re
import sqlite3

from hyperresearch.search.filters import SearchFilters


class SearchQueryError(ValueError):
    """The search query could not be turned into a valid FTS5 query.

    Raised instead of returning an empty result set, so a malformed query is
    never indistinguishable from a topic with no matching notes.
    """


def _split_alphanum(word: str) -> list[str]:
    """Split words where letters meet digits: 'mamba3' -> ['mamba', '3'],
    'gpt4o' -> ['gpt', '4o'], 'llama3.1' -> ['llama', '3', '1'].

    A digit followed by a letter stays one part: text writes 'GPT-4o' or
    'Mamba-3B', which the tokenizer indexes as 'gpt', '4o', so the spaced
    phrase of 'gpt4o' must be 'gpt 4o' to match it.
    """
    # Insert space where a letter meets a digit
    split = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', word)
    # Also split on dots/hyphens between digits (3.1 -> 3 1)
    split = re.sub(r'(\d)[.\-](\d)', r'\1 \2', split)
    return split.split()


def _glued_phrase(word: str) -> str | None:
    """The spaced form of a glued term as one phrase: 'mamba3' -> '"mamba 3"'.

    None when the word does not split. A phrase needs its parts adjacent and
    in order, so 'llama3.1' finds 'Llama 3.1' but not a note that merely holds
    llama, 3 and 1 somewhere, as AND-ed separate terms did.
    """
    subwords = _split_alphanum(word)
    if len(subwords) < 2:
        return None
    return '"' + " ".join(subwords) + '"'


# Quoted phrases (with an optional prefix star), punctuation FTS5 gives meaning
# to in an operator query, and everything else as a bare word. A lone '"' is
# skipped, as the plain path strips it.
_OPERATOR_TOKEN_RE = re.compile(r'"[^"]*"\*?|[(),]|[^\s(),"]+')
# FTS5 barewords: ASCII letters, digits and '_', plus any non-ASCII character.
# Anything else ('-', ':', '.', '/', '^', '+', ...) is FTS5 syntax, so a term
# containing it must be quoted or FTS5 reads 'covid-19' as column '19'.
_BAREWORD_RE = re.compile(r"[0-9A-Za-z_\u0080-\U0010ffff]+")
# A letter or digit. A term without one is an empty phrase to the tokenizer,
# which matches nothing and so empties any explicit AND around it.
_TOKEN_CHAR_RE = re.compile(r"[^\W_]")
# FTS5 operators are case-sensitive: lowercase and/or/not are ordinary terms,
# which is how natural-language queries use them.
_BINARY_OPERATORS = ("AND", "OR", "NOT")


def _is_operator_query(tokens: list[str]) -> bool:
    for i, tok in enumerate(tokens):
        if tok in _BINARY_OPERATORS and 0 < i < len(tokens) - 1:
            return True
        if tok == "NEAR" and tokens[i + 1:i + 2] == ["("]:
            return True
    return False


def _operator_term(word: str) -> str | None:
    """Pass an FTS5 bareword through unchanged; quote anything else as a phrase."""
    core = word.rstrip("*")
    star = "*" if core != word else ""
    if not _TOKEN_CHAR_RE.search(core):
        return None
    if _BAREWORD_RE.fullmatch(core):
        return core + star
    return f'"{core}"{star}'


def _near_group(tokens: list[str], i: int) -> tuple[tuple[str, str] | None, int]:
    """Parse a NEAR group from tokens[i] == 'NEAR' to its ')'.

    Returns the group as an operand (None when every phrase in it dropped
    out) and the index after it. NEAR takes only phrases, so glued terms are
    not expanded here; anything else is kept for FTS5 to reject as before.
    """
    out = ["NEAR", "("]
    phrases = 0
    seen_comma = False
    i += 2
    while i < len(tokens) and tokens[i] != ")":
        tok = tokens[i]
        i += 1
        if tok == ",":
            seen_comma = True
            out.append(tok)
        elif tok.startswith('"'):
            if _TOKEN_CHAR_RE.search(tok):
                out.append(tok)
                phrases += not seen_comma
        elif tok in _BINARY_OPERATORS or tok == "(":
            out.append(tok)
        else:
            term = _operator_term(tok)
            if term:
                out.append(term)
                phrases += not seen_comma
    if i == len(tokens):
        # Unclosed: keep it so FTS5 reports the syntax error.
        return ("raw", " ".join(out)), i
    if not phrases:
        return None, i + 1
    return ("term", " ".join([*out, ")"])), i + 1


def _operator_items(tokens: list[str], i: int, nested: bool) -> tuple[list[tuple[str, str]], int, bool]:
    """Parse operator-mode tokens into ("op" | "term" | "group" | "raw", text)
    items up to the ')' that closes this level.

    Returns the items, the index after them, and whether a ')' closed them.
    A "term" can sit next to another under FTS5's implicit AND; a "group" is
    parenthesized and cannot. A "raw" item is an unbalanced parenthesis, kept
    verbatim so FTS5 still rejects the query.
    """
    items: list[tuple[str, str]] = []
    while i < len(tokens):
        tok = tokens[i]
        if tok in _BINARY_OPERATORS:
            items.append(("op", tok))
            i += 1
        elif tok == "NEAR" and tokens[i + 1:i + 2] == ["("]:
            near, i = _near_group(tokens, i)
            if near:
                items.append(near)
        elif tok == "(":
            inner, i, closed = _operator_items(tokens, i + 1, nested=True)
            text = _join_items(_drop_dangling_operators(inner))
            if not closed:
                items.append(("raw", f"( {text}".rstrip()))
            elif text:
                items.append(("group", f"( {text} )"))
        elif tok == ")":
            if nested:
                return items, i + 1, True
            items.append(("raw", tok))
            i += 1
        elif tok.startswith('"'):
            if _TOKEN_CHAR_RE.search(tok):
                items.append(("term", tok))
            i += 1
        elif tok == ",":
            # Only NEAR(a b, N) gives a comma meaning; elsewhere it is punctuation.
            i += 1
        else:
            term = _operator_term(tok)
            if term:
                core = term.rstrip("*")
                star = term[len(core):]
                phrase = _glued_phrase(core.strip('"'))
                if phrase:
                    items.append(("group", f"({term} OR {phrase}{star})"))
                else:
                    items.append(("term", term))
            i += 1
    return items, i, False


def _drop_dangling_operators(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop operators that lost an operand when a term reduced to nothing.

    'attention AND -' becomes 'attention'. Operators left side by side keep
    the later one, so 'AI AND / OR ML' becomes 'AI OR ML' and 'a AND NOT b',
    which FTS5 rejects, becomes 'a NOT b'.

    A NOT that still has an operand after it is never dropped or replaced:
    'NOT foo AND bar' searched as 'foo AND bar' would return exactly the
    notes it excludes. A leading NOT, or one followed by another operator,
    is kept for FTS5 to reject; only a trailing NOT, with nothing left to
    exclude, goes.
    """
    out: list[tuple[str, str]] = []
    for item in items:
        if item[0] != "op":
            out.append(item)
        elif out and out[-1][0] == "op" and out[-1][1] != "NOT":
            out[-1] = item
        elif out or item[1] == "NOT":
            out.append(item)
    while out and out[-1][0] == "op":
        out.pop()
    return out


def _join_items(items: list[tuple[str, str]]) -> str:
    """Join items, making an implicit AND next to a group explicit.

    FTS5 allows implicit AND only between phrases and NEAR groups, so a run
    of operands holding a group is joined with AND and parenthesized: implicit
    AND binds tighter than every operator, which the parentheses keep.
    """
    out: list[str] = []
    run: list[tuple[str, str]] = []

    def flush() -> None:
        if len(run) > 1 and any(kind == "group" for kind, _ in run):
            out.append("( " + " AND ".join(text for _, text in run) + " )")
        else:
            out.extend(text for _, text in run)
        run.clear()

    for item in items:
        if item[0] == "op":
            flush()
            out.append(item[1])
        else:
            run.append(item)
    flush()
    return " ".join(out)


def _preprocess_operator_query(tokens: list[str]) -> str:
    items, _, _ = _operator_items(tokens, 0, nested=False)
    return _join_items(_drop_dangling_operators(items))


def preprocess_query(raw: str) -> str:
    """Transform user query into FTS5 query syntax.

    - Simple words get prefix matching: 'python async' -> 'python* async*'
    - Glued alphanumeric also matches split: 'mamba3' -> 'mamba3' or 'mamba 3'
    - Quoted phrases stay exact: '"async await"' stays as-is
    - Handles special FTS5 operators: AND, OR, NOT, NEAR (uppercase only).
      Barewords pass through; other terms are quoted ('covid-19' -> '"covid-19"')
    """
    tokens = _OPERATOR_TOKEN_RE.findall(raw)
    if _is_operator_query(tokens):
        return _preprocess_operator_query(tokens)

    parts = re.split(r'(".*?")', raw)
    processed = []
    for part in parts:
        if part.startswith('"'):
            if _TOKEN_CHAR_RE.search(part):
                processed.append(part)
        else:
            words = part.strip().split()
            for word in words:
                if word:
                    # Strip FTS5-special chars that would break syntax. The
                    # double-quote is included because quoted phrases were
                    # already extracted by the outer split — any quote left
                    # here is an unbalanced fragment.
                    clean = re.sub(r'[*^():{}"]', '', word)
                    if not _TOKEN_CHAR_RE.search(clean):
                        continue
                    # Split glued alphanumeric (mamba3 -> "mamba 3") so 'Mamba 3'
                    # matches. unicode61 indexes 'mamba3' as one token, which
                    # the split alone can never match, so accept either form.
                    # The star on the phrase prefixes only its last part.
                    phrase = _glued_phrase(clean)
                    if phrase:
                        processed.append(f'("{clean}"* OR {phrase}*)')
                    else:
                        processed.append(f'"{clean}"*')
    # Explicit AND: FTS5 only allows implicit AND between phrases, not next to
    # a parenthesized group. Implicit AND skipped an empty phrase ('-', '&');
    # explicit AND does not, which is why tokenless terms are dropped above.
    return " AND ".join(processed)


# FTS5's snippet() scores every candidate window against every phrase
# instance in the column, so its cost grows with the square of the matches in
# one body: a prefix query over a 5 MB note took minutes. A body longer than
# this gets its snippet from an excerpt of this many characters instead.
_SNIPPET_MAX_CHARS = 16_000
_SNIPPET_SQL = "snippet(notes_fts, 2, ?, ?, '...', 64)"
# A quoted phrase or a bareword of the FTS5 query, to find a first match.
_QUERY_PART_RE = re.compile(r'"([^"]*)"|([^\W_]+)')
_WORD_RE = re.compile(r"[^\W_]+")


def _first_match(body: str, fts_query: str) -> int:
    """Offset of the first literal occurrence of any query phrase, else 0.

    Only places the excerpt: the tokenizer also stems, so a stemmed-only match
    falls back to the start of the body.
    """
    patterns = []
    for phrase, word in _QUERY_PART_RE.findall(fts_query):
        if word in _BINARY_OPERATORS or word == "NEAR":
            continue
        tokens = _WORD_RE.findall(phrase or word)
        if tokens:
            patterns.append(r"[\W_]+".join(map(re.escape, tokens)))
    if not patterns:
        return 0
    m = re.search(r"(?<![^\W_])(?:" + "|".join(patterns) + ")", body, re.IGNORECASE)
    return m.start() if m else 0


def _excerpt_snippet(
    conn: sqlite3.Connection, fts_query: str, rowid: int,
    snippet_start: str, snippet_end: str,
) -> str:
    """snippet() for a body over _SNIPPET_MAX_CHARS, run on a copy of the row
    whose body is cut to an excerpt starting shortly before the first match.

    The copy lives in a throwaway in-memory table built from the vault's own
    notes_fts definition, so tokenizing and highlighting match snippet().
    """
    row = conn.execute(
        "SELECT title, body_plain, tags, aliases FROM notes_fts WHERE rowid = ?", (rowid,)
    ).fetchone()
    if row is None:
        # A sync from another process rewrote the row (new rowid) after the
        # search query ran: leave the snippet empty rather than fail.
        return ""
    body = row[1] or ""
    start = max(0, _first_match(body, fts_query) - _SNIPPET_MAX_CHARS // 4)
    end = min(len(body), start + _SNIPPET_MAX_CHARS)
    # Cut at whitespace so no word is split into a token the body does not hold.
    if start > 0:
        space = body.find(" ", start)
        start = space + 1 if 0 <= space < end else start
    if end < len(body):
        space = body.rfind(" ", start, end)
        end = space if space > start else end
    excerpt = body[start:end]

    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'notes_fts'"
    ).fetchone()[0]
    scratch = sqlite3.connect(":memory:")
    try:
        scratch.execute(schema)
        scratch.execute(
            "INSERT INTO notes_fts (title, body_plain, tags, aliases) VALUES (?, ?, ?, ?)",
            (row[0], excerpt, row[2], row[3]),
        )
        hit = scratch.execute(
            f"SELECT {_SNIPPET_SQL} FROM notes_fts WHERE notes_fts MATCH ?",
            (snippet_start, snippet_end, fts_query),
        ).fetchone()
    finally:
        scratch.close()

    if hit:
        snippet = hit[0]
    else:
        # The match lies outside the excerpt: show its start, as snippet()
        # does for a body the query does not match.
        words = excerpt.split()
        snippet = " ".join(words[:64]) + ("..." if len(words) > 64 else "")
    # snippet() marks only the excerpt's own edges as cut.
    if start > 0 and not snippet.startswith("..."):
        snippet = "..." + snippet
    if end < len(body) and not snippet.endswith("..."):
        snippet += "..."
    return snippet


def _fts_rejects(conn: sqlite3.Connection, fts_query: str) -> bool:
    """True when FTS5 rejects this MATCH expression on an index that works.

    FTS5 reports query errors under many messages ('no such column: 19',
    'expected integer, got ...', 'unknown special query'), some shared with a
    broken vault, so the message alone cannot classify them. A trivial MATCH
    that succeeds proves the index is readable and the expression is at fault.
    """
    probe = "SELECT 1 FROM notes_fts WHERE notes_fts MATCH ? LIMIT 1"
    try:
        conn.execute(probe, ("a",)).fetchall()
    except sqlite3.OperationalError:
        return False
    try:
        conn.execute(probe, (fts_query,)).fetchall()
    except sqlite3.OperationalError:
        return True
    return False


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    *,
    filters: SearchFilters | None = None,
    limit: int = 20,
    offset: int = 0,
    include_index: bool = False,
    ranking: dict | None = None,
    quality_ranked: bool = False,
    snippet_start: str = ">>>",
    snippet_end: str = "<<<",
) -> list[dict]:
    """Execute a full-text search against the notes_fts table.

    Raises:
        SearchQueryError: the query has no searchable terms, unless it is blank
            and at least one metadata filter is supplied.
        sqlite3.OperationalError: the FTS index is missing or unreadable. This is
            deliberately not swallowed — a broken index must not look like a
            topic with no results.
    """
    fts_query = preprocess_query(query)

    where, filter_params = filters.to_sql("n") if filters else ("1=1", [])
    filter_only = not query.strip() and where != "1=1"
    if not fts_query.strip() and not filter_only:
        raise SearchQueryError(
            f"Search query {query!r} contains no searchable terms. "
            "Provide at least one word, quoted phrase, or a filter without a text query."
        )
    filter_clause = f"AND {where}"

    # Exclude auto-generated index pages by default
    index_clause = "" if include_index else "AND n.type != 'index'"

    # BM25 column weights from config (id=unindexed=0, title, body, tags, aliases)
    w = ranking or {}
    tw = w.get("title_weight", 10.0)
    bw = w.get("body_weight", 1.0)
    tgw = w.get("tags_weight", 5.0)
    aw = w.get("aliases_weight", 3.0)

    # The status multipliers and the --ranked quality factor are part of the
    # score SQL orders and pages by. Re-sorting only the fetched rows after
    # LIMIT/OFFSET made a page disagree with the full ranking.
    score_factors: list[str] = []
    score_params: list[float] = []
    if ranking and not filter_only:
        score_factors.append(
            "CASE n.status WHEN 'evergreen' THEN ? WHEN 'deprecated' THEN ? "
            "WHEN 'stale' THEN ? ELSE 1.0 END"
        )
        score_params += [
            ranking.get("boost_evergreen", 1.0),
            ranking.get("penalize_deprecated", 1.0),
            ranking.get("penalize_stale", 1.0),
        ]
    # Fold the composite source-quality score into relevance. (0.5 + quality)
    # keeps unscored notes (quality NULL -> neutral 1.0x via fallback 0.5)
    # competitive while a ground-truth-tier, high-authority source (~1.0)
    # roughly triples a retracted one (~0.05).
    if quality_ranked and not filter_only:
        score_factors.append("(0.5 + COALESCE(n.quality_score, 0.5))")

    source = "notes n" if filter_only else "notes_fts fts JOIN notes n ON fts.id = n.id"
    match = "1=1" if filter_only else "notes_fts MATCH ?"
    # A long body's snippet stays NULL here and is built from an excerpt below.
    snippet = "COALESCE(n.summary, '')" if filter_only else (
        f"CASE WHEN length(fts.body_plain) <= {_SNIPPET_MAX_CHARS} THEN {_SNIPPET_SQL} END"
    )
    fts_rowid = "NULL" if filter_only else "fts.rowid"
    score = "0.0" if filter_only else " * ".join(
        [f"abs(bm25(notes_fts, 0.0, {tw}, {bw}, {tgw}, {aw}))", *score_factors]
    )
    order = "n.created DESC, n.id" if filter_only else "score DESC"
    sql = f"""
        SELECT
            n.id, n.title, n.path, n.status, n.type, n.tier, n.content_type,
            n.quality_score, n.doi, n.venue, n.citation_count, n.is_retracted, n.oa_version,
            n.created, n.updated, n.word_count, n.summary,
            {snippet} as snippet,
            {fts_rowid} as fts_rowid,
            {score} as score,
            (SELECT json_group_array(t.tag) FROM tags t WHERE t.note_id = n.id) as tag_list
        FROM {source}
        WHERE {match}
        {filter_clause}
        {index_clause}
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """

    params = [
        *([snippet_start, snippet_end] if not filter_only else []),
        *score_params, *([fts_query] if not filter_only else []), *filter_params, limit, offset,
    ]

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if not filter_only and _fts_rejects(conn, fts_query):
            raise SearchQueryError(f"Invalid search query {query!r}: {exc}") from exc
        # Missing table, corrupt index, locked database — surface it. Returning []
        # here previously made a broken vault indistinguishable from an empty one.
        raise

    results = []
    for row in rows:
        tag_list = json.loads(row["tag_list"]) if row["tag_list"] else []
        snippet = row["snippet"]
        if snippet is None and not filter_only:
            snippet = _excerpt_snippet(conn, fts_query, row["fts_rowid"], snippet_start, snippet_end)
        results.append({
            "id": row["id"],
            "title": row["title"],
            "path": row["path"],
            "status": row["status"],
            "type": row["type"],
            # sqlite3.Row.__contains__ is broken; row.keys() is reliable.
            "tier": row["tier"] if "tier" in row.keys() else None,  # noqa: SIM118
            "content_type": row["content_type"] if "content_type" in row.keys() else None,  # noqa: SIM118
            "doi": row["doi"],
            "venue": row["venue"],
            "citation_count": row["citation_count"],
            "is_retracted": None if row["is_retracted"] is None else bool(row["is_retracted"]),
            "oa_version": row["oa_version"],
            "tags": tag_list,
            "created": row["created"],
            "updated": row["updated"],
            "word_count": row["word_count"],
            "summary": row["summary"],
            "quality_score": row["quality_score"] if "quality_score" in row.keys() else None,  # noqa: SIM118
            "score": row["score"],
            "snippet": snippet or "",
        })

    return results
