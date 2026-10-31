import json

import pytest

from hyperresearch.core.runs import RunError, init_run
from hyperresearch.core.vault import InvalidRunTagError, validate_run_tag


def test_run_tags_reject_uppercase():
    with pytest.raises(InvalidRunTagError, match="lowercase"):
        validate_run_tag("Topic-aaaaaa")


def test_init_rejects_existing_manifest_for_different_tag(tmp_vault):
    tag = "topic-aaaaaa"
    init_run(tmp_vault, tag)
    manifest = tmp_vault.run_dir(tag) / "run.json"
    data = json.loads(manifest.read_text())
    data["vault_tag"] = "Topic-aaaaaa"
    manifest.write_text(json.dumps(data))
    original = manifest.read_bytes()
    with pytest.raises(RunError, match="collision"):
        init_run(tmp_vault, tag)
    assert manifest.read_bytes() == original
