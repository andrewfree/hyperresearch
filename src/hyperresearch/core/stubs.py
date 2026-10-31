"""Create notes whose titles and aliases resolve broken references."""

from hyperresearch.core.note import indexed_note_ids, read_note, stub_summary, write_note


def create_stubs(
    vault, targets: list[str], *, skip_errors: bool = False,
) -> tuple[list[dict], list[dict]]:
    groups: dict[str, list[str]] = {}
    for target in targets:
        title = target.split("#", 1)[0].strip()
        groups.setdefault(title.lower(), []).append(target)

    created, errors = [], []
    taken = indexed_note_ids(vault.db)
    for refs in groups.values():
        title = refs[0].split("#", 1)[0].strip()
        try:
            path = write_note(
                vault.temp_dir, title,
                body=f"# {title}\n\n*Stub - created to resolve a broken link. Expand this note.*\n",
                note_id=title, status="draft", summary=stub_summary(title),
                # SQLite LOWER only folds ASCII, unlike the grouping above.
                # Keep every spelling, including full heading fragments.
                extra_frontmatter={"aliases": [ref for ref in refs if ref != title]},
                taken_ids=taken,
            )
            note = read_note(path, vault.root)
            taken.add(note.meta.id)
            created.append({"id": note.meta.id, "title": title,
                            "path": path.relative_to(vault.root).as_posix()})
        except Exception as exc:
            if not skip_errors:
                raise
            errors.append({"target": refs[0], "error": str(exc)})
    return created, errors
