# Maintaining the Hyperresearch fork

## What this fork is

[andrewfree/hyperresearch](https://github.com/andrewfree/hyperresearch) is a maintained fork of [jordan-gibbs/hyperresearch](https://github.com/jordan-gibbs/hyperresearch). It carries bug fixes while upstream reviews them. Hyperresearch is a Python CLI for research vaults: markdown notes are the source of truth, and SQLite is a derived cache.

The sweep starts from upstream `aece65f`, v0.13.0. The high-severity fix series through `7644d5e` was also submitted as [upstream PR #187](https://github.com/jordan-gibbs/hyperresearch/pull/187), open at this guide's baseline. Its existing entries remain in the changelog's `Fixed` list.

Wave 1, fork PRs #2 through #8, added 80 non-merge commits addressing medium- and low-severity findings. Claude Opus 5.5 agents implemented and reviewed them, GPT-6 Astra reviewed sync-vault, and GPT-6.1 Sol supplied a Python 3.11 compatibility fix. Wave 2, fork PRs #9 and #10, contains implementation and review corrections by GPT-6.1 Sol and GPT-6 Astra through the Codex CLI. The [fork changelog](CHANGELOG.md#fixed-in-this-fork-andrewfreehyperresearch) records the resulting user-visible fixes, including review corrections.

At a glance, the fixes cover note preservation, sync and moves, search, links and graph reports, the viewer and MCP, installation, run state and fetching. Compatibility changes to account for are:

- Remote viewer images are blocked by default. To enable them, set `allow_remote_images = true` under `[viewer]` in the vault's `.hyperresearch/config.toml`. Edit the TOML file directly; `config set` does not expose `viewer.allow_remote_images`. Blocked images become links, and rendered images suppress referrers.
- `a OR NOT b` returns `BAD_QUERY` instead of silently becoming a narrower search. A leading `NOT` with an operand is rejected; `a AND NOT b` and quoted operator text remain supported.
- A punctuation-only search returns `BAD_QUERY` instead of an empty successful result, as established in the earlier high-severity fixes. Mixed Boolean queries now discard operators left dangling by removed punctuation, so `attention AND -` searches for `attention`.
- Glued terms match adjacent split forms: `gpt4o` matches `GPT-4o`, while plain `3d` no longer expands to `3-D`.
- Generated index links no longer count toward citation, backlink, connectivity or promotion decisions.
- Blank `link --tag` or `--note` values return `NO_INPUT` instead of selecting the whole vault.
- `lint --fix` is removed because it never changed anything; an unknown `--rule` now returns `UNKNOWN_RULE`.
- The earlier high-severity fixes moved non-slug tag index filenames to `_tag-<slug>.md`, with digest names for collisions. Ordinary slug tags keep their filenames.
- The viewer accepts only `127.0.0.1`, `localhost` or `[::1]` Host names, optionally with a port; other hosts receive 403.
- Run tags must use lowercase letters; a manifest with a different stored tag is refused.
- Escalation ingest accepts only claimed items; queued, human-waiting and already resolved items are refused.
- `init --dir` requires a subdirectory inside the vault, outside `.hyperresearch`, `.git`, `.claude`, `.codex` and `.agents`. Existing root-directory research layouts still sync with those internals excluded.

## Branch model and remotes

Fork `main` is upstream main plus the fork's fixes. Every change to fork main lands through a PR on `andrewfree/hyperresearch`.

In the maintainer's checkout, the names are deliberately different from a typical fork clone:

| Name | Repository or tracking target |
| --- | --- |
| `origin` | `jordan-gibbs/hyperresearch`, upstream |
| `fork` | `andrewfree/hyperresearch`, this fork |
| Local `main` | Tracks `fork/main` |

Check the checkout before using the procedures below:

```sh
git remote -v
git status --short
git branch -vv
```

Confirm that local `main` tracks `fork/main`; the procedures below assume this layout. Review clones and fresh clones may use different remote names. Start with a clean working tree. Push fork branches to `fork` and always name the repository in GitHub CLI and local-ci commands, since `origin` points upstream. The commands below are maintainer procedures for a network-enabled checkout.

## CI

GitHub Actions is disabled on the fork. The workflow in `.github/workflows/ci.yml` remains the suite definition, and local-ci gates every fork PR.

Before opening a PR, run the complete test suite in environments for the oldest and newest supported Python versions, 3.11 and 3.14, with the pytest cache plugin enabled:

```sh
pytest tests/ -q
```

Run that command once in each environment. Do not add `-p no:cacheprovider`. This fork once shipped a test that passed on Python 3.14 with the cache plugin disabled and broke CI on Python 3.11. The cache plugin exposed the test's change to global platform state. Match CI's test selection and plugin behavior; the workflow uses `pytest tests/ -v`, which differs in verbosity.

The workflow also checks lint and builds the package. The PR gate runs the configured jobs through local-ci:

```sh
local-ci run --pr <N> --repo andrewfree/hyperresearch
local-ci gate --pr <N> --repo andrewfree/hyperresearch
```

Replace `<N>` with the fork PR number. Run the potentially long CI job in the background and retain its output. Interpret the gate's exit code as follows:

| Exit | Action |
| --- | --- |
| 0 | CI is satisfied; the PR may be merged. |
| 4 | Run local-ci for the PR, then gate again. |
| 3 | Checks are still running; wait, then gate again. |
| 1 | A real test or check failed; investigate and fix it. |
| 2 | local-ci or the runner broke; retry once, then use `local-ci doctor` if it repeats. |

Merge only on gate exit 0, and gate again if the base branch changes. local-ci cannot run the `windows-latest` job, currently Python 3.11. It lists that job as unsupported in the PR report; it does not block merging and does not provide Windows verification.

## Syncing with upstream

Fetch both repositories, then create the sync branch from the fork's current main:

```sh
git fetch origin
git fetch fork
sync_branch="sync/upstream-$(date +%Y-%m-%d)"
git switch -c "$sync_branch" fork/main
git merge origin/main
```

If the merge reports conflicts, edit the conflicting files, preserve unrelated upstream changes, then stage the resolved tracked files and complete the merge:

```sh
git add -u
git merge --continue
```

The commits submitted in upstream #187 have the same SHAs on fork main. If upstream merges that PR while preserving those commits, Git recognizes the shared history without duplicating them. If upstream squashes it, Git sees a separate commit containing overlapping changes. For conflicts in those fixes, keep the fork's side of the affected hunks, retain unrelated upstream changes, complete the merge, then confirm the combined tree with the full suite on Python 3.11 and 3.14. Do not replace whole files with the fork's version if doing so would discard other upstream work.

After the merge and both test runs, publish the sync branch and open a fork PR:

```sh
git push -u fork "$sync_branch"
gh pr create --repo andrewfree/hyperresearch --base main --head "$sync_branch" --title "Sync upstream main" --body "Merge origin/main into fork/main. Full test suite checked on Python 3.11 and 3.14 with the pytest cache plugin enabled."
local-ci run --pr <N> --repo andrewfree/hyperresearch
local-ci gate --pr <N> --repo andrewfree/hyperresearch
```

Use the PR number returned by `gh pr create`. Only after gate exit 0, merge using a merge commit so the upstream ancestry is retained:

```sh
gh pr merge <N> --repo andrewfree/hyperresearch --merge
git fetch fork
git switch main
git merge --ff-only fork/main
```

Local main continues to track `fork/main`. If the fast-forward is refused, inspect local commits before changing the branch.

## Sending a fix upstream

The maintainer decides whether and when to send a fix upstream. Landing a fork PR does not authorize opening an upstream PR.

When that decision is made, start from current upstream main and cherry-pick only the relevant fork commits in dependency order, oldest first:

```sh
git fetch origin
git switch -c upstream/fix-name origin/main
git cherry-pick <sha>
```

Replace `fix-name` with a descriptive branch name and `<sha>` with a fork fix commit. Repeat the cherry-pick for each required commit, including review corrections that the fix depends on. If a pick conflicts, resolve the files, run `git add -u`, and finish it with `git cherry-pick --continue`.

Run `pytest tests/ -q` on Python 3.11 and 3.14 with the cache plugin enabled. Then push the export branch to the fork and open the upstream PR:

```sh
git push -u fork upstream/fix-name
gh pr create --repo jordan-gibbs/hyperresearch --base main --head andrewfree:upstream/fix-name --title "Fix the reported behavior" --body "Describe the user-visible defect, the fix, and validation on Python 3.11 and 3.14."
```

Use a concrete title and body for the selected fix. Do not submit unrelated sweep commits or fork-only maintenance policy.

## Installing and developing

Supported Python versions are 3.11 through 3.14, matching `requires-python = ">=3.11,<3.15"` in `pyproject.toml`. Install the maintained fork from main:

```sh
pip install git+https://github.com/andrewfree/hyperresearch@main
```

For development, use a virtual environment with a supported interpreter and run this from the repository root:

```sh
pip install -e ".[dev]"
pytest tests/ -q
```

The `dev` extra provides pytest and the development tools. Test both supported endpoints before opening a PR, and use the local-ci gate for the PR itself.

## Known issues and deliberate trade-offs

- Plain `3d` no longer matches `3-D` through query expansion because digit-letter splitting was dropped so `gpt4o` matches `GPT-4o`.
- An AND search whose terms lie far apart in a very large note can return a matching note with an excerpt that has no highlights because the excerpt does not contain the entire query.
- On Windows, replacing an index page can fail if another process holds it open without allowing deletion or replacement.
- Crawl4AI navigation failures can carry the provider's full, long error text into fetch-batch output.
- A move combined with an edit in the same sync is treated as a delete plus an add, so the note's stored claims are not carried over.
- After an external file removal, a byte-identical, never-indexed copy with the same id can inherit the removed note's stored rows because sync cannot distinguish it from a move; explicit `note rm` clears those rows first.
- Old skills and agents without the rendered-profile provenance header are left in place during pruning and must be removed manually if no longer wanted.
