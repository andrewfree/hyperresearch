"""Batch fetch — fetch multiple URLs in one command with batched sync."""

from __future__ import annotations

import hashlib
import sys
from urllib.parse import urlparse

import typer
from rich.markup import escape

from hyperresearch.cli._output import console, output
from hyperresearch.core.fetcher import (
    discard_unindexed_note,
    existing_live_note_for_url,
    reclaim_orphaned_source_row,
)
from hyperresearch.models.output import error, success


def fetch_batch(
    urls: list[str] = typer.Argument(None, help="URLs to fetch"),
    stdin: bool = typer.Option(False, "--stdin", help="Read URLs from stdin (one per line)"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags for all notes"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    provider_name: str | None = typer.Option(None, "--provider", help="Web provider override"),
    save_assets: bool = typer.Option(False, "--save-assets", "-a", help="Download images and screenshots"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Fetch multiple URLs and save each as a research note. Batched sync for speed."""
    from hyperresearch.core.enrich import enrich_note_file
    from hyperresearch.core.note import indexed_note_ids, write_note
    from hyperresearch.core.oa import (
        oa_frontmatter,
        recover_full_text,
        recovery_notice,
        rescue_full_text,
    )
    from hyperresearch.core.scholar import extract_doi
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.cli.fetch import (
        _detect_content_type,
        _detect_tier,
        _escalate_blocked,
        _junk_escalation_reason,
        _save_raw_file,
        _url_parse_error,
    )
    from hyperresearch.core.vault import Vault, VaultError
    from hyperresearch.web.base import get_provider
    from hyperresearch.web.pdf import PDF_FAILURE_KEY

    # Collect URLs from args and/or stdin
    all_urls = list(urls or [])
    if stdin:
        for line in sys.stdin:
            line = line.strip()
            if line and line.startswith("http"):
                all_urls.append(line)
    # Each distinct URL once: a repeat would be fetched and written as a second
    # note whose sources row Phase 3 cannot insert.
    all_urls = list(dict.fromkeys(all_urls))

    if not all_urls:
        if json_output:
            output(error("No URLs provided", "NO_INPUT"), json_mode=True)
        else:
            console.print("[red]No URLs provided.[/] Pass URLs as arguments or use --stdin.")
        raise typer.Exit(1)

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()
    conn = vault.db

    failed_urls: list[dict] = []  # surfaced in JSON output so callers see what was lost

    def _fail(url: str, error: str, kind: str) -> None:
        failed_urls.append({"url": url, "error": error, "phase": kind})
        if not json_output:
            console.print(f"  [red]Failed ({kind}):[/] {url} — {error}")

    # A URL urlparse rejects would crash the provider, extract_doi and the
    # visible-domain check alike, and take the whole batch down with it.
    valid_urls = []
    for url in all_urls:
        parse_error = _url_parse_error(url)
        if parse_error:
            _fail(url, parse_error, "input")
        else:
            valid_urls.append(url)

    def _needs_visible(fetch_url: str) -> bool:
        if not vault.config.web_profile:
            return False
        domain = urlparse(fetch_url).netloc.lower()
        return any(d in domain for d in vault.config.fetch.visible_browser_domains)

    prov = get_provider(
        provider_name or vault.config.web_provider,
        profile=vault.config.web_profile,
        magic=vault.config.web_magic,
        settings=vault.config.fetch,
        gates=vault.config.junk,
    )

    # Filter out already-fetched URLs
    new_urls = []
    for url in valid_urls:
        # An orphaned row (note deleted) is not a duplicate; only a live note skips
        existing = existing_live_note_for_url(conn, url)
        if existing:
            if not json_output:
                console.print(f"  [dim]Skip:[/] {url} (already fetched as {existing['note_id']})")
        else:
            new_urls.append(url)

    if not new_urls and not failed_urls:
        if json_output:
            output(success({"notes_created": [], "skipped": len(all_urls)}, vault=str(vault.root)), json_mode=True)
        else:
            console.print("[dim]All URLs already fetched.[/]")
        return

    if new_urls and not json_output:
        console.print(f"[bold]Fetching {len(new_urls)} URLs with {prov.name}...[/]")

    # Split URLs into normal (headless batch) and auth-aggressive (visible, sequential)
    normal_urls = [u for u in new_urls if not _needs_visible(u)]
    visible_urls = [u for u in new_urls if _needs_visible(u)]

    # (requested url, result). The requested url is what gets recorded and
    # deduped on, as in cli/fetch.py; result.url can be a redirect target.
    results = []

    def _fetch_one(provider, url: str, kind: str) -> None:
        try:
            results.append((url, provider.fetch(url)))
        except Exception as exc:
            _fail(url, str(exc), kind)

    # Batch fetch normal URLs
    if normal_urls:
        if hasattr(prov, "fetch_many"):
            try:
                batch = prov.fetch_many(normal_urls)
                # fetch_many answers in completion order, so each result names
                # the input it belongs to.
                results.extend((r.requested_url or r.url, r) for r in batch)
                # The URLs it gave up on (SSRF refusal, failed navigation, ...)
                for f in getattr(batch, "failures", ()):
                    _fail(f["url"], f["error"], "batch")
            except Exception as e:
                # fetch_many can return zero results on a single bad URL
                # inside the batch comprehension. Fall back to per-URL so we
                # don't silently lose the entire wave — partial progress
                # beats none.
                if not json_output:
                    console.print(
                        f"[red]Batch fetch failed:[/] {e}. Falling back to per-URL fetches."
                    )
                for url in normal_urls:
                    _fetch_one(prov, url, "batch-fallback")
        else:
            for url in normal_urls:
                _fetch_one(prov, url, "normal")

    # Fetch auth-aggressive URLs with visible browser (sequential)
    if visible_urls:
        visible_prov = get_provider(
            provider_name or vault.config.web_provider,
            profile=vault.config.web_profile,
            magic=vault.config.web_magic,
            headless=False,
            settings=vault.config.fetch,
            gates=vault.config.junk,
        )
        for url in visible_urls:
            _fetch_one(visible_prov, url, "visible")

    # Every input ends up created, skipped or failed. A provider that returns
    # neither a result nor a failure for a URL has still lost it.
    answered = {u for u, _ in results} | {f["url"] for f in failed_urls}
    for url in new_urls:
        if url not in answered:
            _fail(url, "the provider returned no result for this URL", "batch")

    # Partition into what can be written and what was blocked. Blocked sources
    # get one open-access rescue attempt before being written off — see
    # cli/fetch.py for the reasoning. It matters more here: the pipeline fetches
    # in waves through this command, so one bot-walled publisher silently drops
    # a whole cluster of papers at once.
    pending = []  # (url, result, oa_location, rescue_reason)
    # An unparseable input has no DOI to rescue it with.
    blocked = [
        (f["url"], f"fetch failed: {f['error']}", None)
        for f in failed_urls if f["phase"] != "input"
    ]
    # url -> (failed_urls phase, escalation reason or None, error) for a result
    # one of cli/fetch.py's gates refused. A fetch that raised is in
    # failed_urls already, so it has no entry here.
    refusals: dict[str, tuple[str, str | None, str]] = {}

    for url, result in results:
        # The gates cli/fetch.py applies, in the same order.
        if result.looks_like_login_wall(url, vault.config.junk):
            reason = f"login wall: {result.title}"
            blocked.append((url, reason, result.raw_html))
            refusals[url] = ("auth", "login_wall", reason)
            continue
        junk_reason = result.looks_like_junk(vault.config.junk)
        if junk_reason:
            blocked.append((url, junk_reason, result.raw_html))
            # A PDF that failed its own lane lands here as binary garbage; say
            # why the PDF lane declined it, as cli/fetch.py does (#82).
            pdf_failure = result.metadata.get(PDF_FAILURE_KEY)
            error_text = f"{junk_reason}. PDF lane: {pdf_failure}" if pdf_failure else junk_reason
            refusals[url] = ("junk", _junk_escalation_reason(junk_reason), error_text)
            continue
        pending.append((url, result, None, None))

    rescued_urls: set[str] = set()
    for burl, reason, raw_html in blocked:
        # URL and meta tags only — a wall page's body carries no DOI worth
        # trusting.
        rescued, loc = rescue_full_text(vault, prov, burl, extract_doi(burl, raw_html, None))
        if rescued is None:
            refusal = refusals.get(burl)
            if refusal is None:
                continue
            # Lost to a gate: report it and queue it for the browser lane, as
            # cli/fetch.py does, instead of dropping it.
            phase, escalation_reason, error_text = refusal
            item_id = None
            if escalation_reason:
                item_id = _escalate_blocked(
                    vault, burl, escalation_reason, tags, [], None, detail=reason
                )
            queued = f" Queued for browser-lane escalation (#{item_id})." if item_id else ""
            failed_urls.append({"url": burl, "error": error_text + "." + queued, "phase": phase})
            if not json_output:
                if phase == "auth":
                    console.print(
                        f"  [yellow]Auth required:[/] {burl}: login page detected, skipping. "
                        f"Run 'hyperresearch setup' to create a login profile.{queued}"
                    )
                else:
                    console.print(f"  [yellow]Skipped:[/] {burl}: {error_text}.{queued}")
            continue
        pending.append((burl, rescued, loc, reason))
        rescued_urls.add(burl)
        if not json_output:
            console.print(
                f"  [cyan]Blocked — recovered an open-access copy:[/] {burl} "
                f"(via {loc.resolver})"
            )

    # A rescued URL is no longer lost, so it should not still be reported as a
    # failure to the caller.
    failed_urls[:] = [f for f in failed_urls if f["url"] not in rescued_urls]

    # Phase 1: Write all note files to disk (no sync yet)
    # (note_path, url, result, domain, content_hash, oa_location, rescue_reason, raw_file)
    note_files = []
    # Ids written in this batch exist on disk, which write_note checks itself.
    taken_ids = indexed_note_ids(conn)
    for url, result, oa_location, rescue_reason in pending:
        # Open-access recovery. This path writes its own notes rather than
        # going through cli.fetch, so the DOI capture and the OA swap both have
        # to be repeated here — and they matter more here, because the pipeline
        # fetches in waves through this command.
        if oa_location is None:
            detected_doi = extract_doi(url, result.raw_html, result.content)
            original_domain = result.domain
            original_chars = len(result.content or "")
            result, oa_location = recover_full_text(vault, prov, url, detected_doi, result)
        else:
            # Rescued: nothing was read from the source, so its domain comes
            # from the URL and there is no original length to report.
            detected_doi = extract_doi(url, None, None)
            original_domain = urlparse(url).netloc.lower()
            original_chars = 0

        title = result.title or urlparse(url).path.split("/")[-1] or "Untitled"
        domain = original_domain
        detected_content_type = _detect_content_type(url, result.raw_content_type)
        detected_tier = _detect_tier(url, detected_content_type)

        extra_meta = {
            "source": url,
            "source_domain": domain,
            "fetched_at": result.fetched_at.isoformat(),
            "fetch_provider": prov.name,
        }
        if detected_doi:
            extra_meta["doi"] = detected_doi

        body_content = result.content
        if oa_location is not None:
            extra_meta.update(
                oa_frontmatter(
                    oa_location, kind="rescued" if rescue_reason else "substituted"
                )
            )
            body_content = (
                recovery_notice(
                    oa_location, url, original_chars, blocked_reason=rescue_reason
                )
                + "\n"
                + body_content
            )

        note_path = write_note(
            vault.notes_dir,
            title=title,
            body=body_content,
            tags=tags,
            status="draft",
            source=url,
            parent=parent,
            tier=detected_tier,
            content_type=detected_content_type,
            extra_frontmatter=extra_meta,
            taken_ids=taken_ids,
        )

        # Auto-enrich before sync
        enrich_note_file(note_path, conn, tags)
        # After enrich, which rewrites the frontmatter
        raw_file_path = _save_raw_file(vault, note_path, result)

        content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]
        note_files.append(
            (note_path, url, result, domain, content_hash, oa_location, rescue_reason,
             raw_file_path)
        )

        if not json_output:
            console.print(f"  [green]+[/] {title}")
            if oa_location is not None:
                console.print(
                    f"    [cyan]body from:[/] {oa_location.url} "
                    f"({oa_location.version or 'version unknown'}, via {oa_location.resolver})"
                )
                if rescue_reason:
                    console.print(
                        f"    [yellow]source never read[/] ({rescue_reason}) — "
                        "title and authors are the open-access copy's too"
                    )

    # Phase 2: ONE sync to index all notes
    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    # A note sync did not index under its own id gets no source row: the row
    # would point at whichever file holds that id. Checked before Phase 3,
    # whose inserts open a transaction the clean-up's re-sync cannot nest in.
    indexed_files = []
    for entry in note_files:
        refused = discard_unindexed_note(vault, entry[0], entry[7])
        if refused is None:
            indexed_files.append(entry)
            continue
        failed_urls.append({"url": entry[1], "error": refused, "phase": "index"})
        if not json_output:
            console.print(f"  [red]Not indexed:[/] {escape(refused)}")
    note_files = indexed_files

    # Phase 3: Bulk-insert source records
    created_notes = []
    lost_races = []  # (note_path, raw_file, url, winner note id)
    for (
        note_path, url, result, domain, content_hash, oa_location, rescue_reason, raw_file_path,
    ) in note_files:
        note_id = note_path.stem
        conn.execute(
            """INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash),
        )
        # The INSERT is also a no-op on an orphaned row (note deleted); claim it
        reclaim_orphaned_source_row(
            conn, url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash
        )
        # Another fetch can record the url between the duplicate check and the
        # INSERT above, which is then a no-op. As in cli/fetch.py, the winner
        # keeps the url and this batch's note goes.
        winner = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
        if winner is not None and winner["note_id"] != note_id:
            lost_races.append((note_path, raw_file_path, url, winner["note_id"]))
            continue

        # Save assets if requested
        if save_assets:
            from hyperresearch.cli.fetch import _save_assets as _save_assets_fn

            assets_dir = vault.root / "research" / "assets" / note_id
            _save_assets_fn(
                conn, result, note_id, assets_dir,
                settings=vault.config.assets,
                image_timeout_s=vault.config.fetch.image_timeout_s,
                max_image_bytes=vault.config.fetch.max_image_bytes,
                allow_private_hosts=vault.config.fetch.allow_private_hosts,
            )

        entry = {
            "note_id": note_id,
            "title": result.title or "Untitled",
            "url": url,
            "domain": domain,
            "word_count": len(result.content.split()),
            "raw_file": raw_file_path,
        }
        if oa_location is not None:
            entry["oa"] = {
                "url": oa_location.url,
                "resolver": oa_location.resolver,
                "version": oa_location.version,
                "license": oa_location.license,
                "kind": "rescued" if rescue_reason else "substituted",
                "nothing_from_source": bool(rescue_reason),
                "blocked_reason": rescue_reason,
            }
        created_notes.append(entry)

    conn.commit()

    # Drop the race losers after the commit: the re-sync cannot run inside the
    # transaction Phase 3's inserts opened.
    if lost_races:
        for note_path, raw_file_path, url, winner_id in lost_races:
            note_path.unlink(missing_ok=True)
            if raw_file_path:
                (vault.root / "research" / raw_file_path).unlink(missing_ok=True)
            if not json_output:
                console.print(f"  [dim]Skip:[/] {url} (already fetched as {winner_id})")
        plan = compute_sync_plan(vault)
        if plan.to_delete:
            execute_sync(vault, plan)
    skipped = len(valid_urls) - len(new_urls) + len(lost_races)

    # Phase 4: Auto-link across all new notes
    if created_notes:
        from hyperresearch.core.linker import auto_link

        note_ids = [n["note_id"] for n in created_notes]
        link_report = auto_link(vault, note_ids)
        if link_report:
            plan = compute_sync_plan(vault)
            if plan.to_add or plan.to_update:
                execute_sync(vault, plan)

    oa_recovered = sum(1 for n in created_notes if "oa" in n)
    oa_rescued = sum(1 for n in created_notes if n.get("oa", {}).get("kind") == "rescued")
    data = {
        "notes_created": created_notes,
        "total_fetched": len(created_notes),
        "skipped": skipped,
        "failed_urls": failed_urls,
        "oa_recovered": oa_recovered,
        "oa_rescued": oa_rescued,
    }

    if json_output:
        output(success(data, count=len(created_notes), vault=str(vault.root)), json_mode=True)
    else:
        msg = (
            f"\n[bold]Done:[/] {len(created_notes)} notes created, "
            f"{skipped} skipped (already fetched)"
        )
        if failed_urls:
            msg += f", [red]{len(failed_urls)} failed[/]"
        if oa_recovered:
            msg += (
                f"\n[cyan]{oa_recovered} note(s) carry an open-access full text in place of a "
                "paywalled page[/] — each one says so in its body banner and oa_* frontmatter."
            )
        if oa_rescued:
            msg += (
                f"\n[yellow]{oa_rescued} of those had a source that could not be read at all[/] "
                "— those notes are entirely the open-access copy, titles and authors included."
            )
        console.print(msg + ".")
