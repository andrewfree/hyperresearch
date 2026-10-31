"""Built-in note templates."""

from __future__ import annotations

from datetime import UTC

BUILTIN_TEMPLATES: dict[str, str] = {
    "note": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: note
created: {{ created }}
---

# {{ title }}

""",
    "concept": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: note
summary: ""
created: {{ created }}
---

# {{ title }}

## Definition

_What is this concept?_

## Key Properties

-

## Examples

-

## Related

- [[]]
""",
    "reference": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: raw
source: ""
summary: ""
created: {{ created }}
---

# {{ title }}

## Citation

_Author, Title, Year. URL._

## Key Points

-

## Quotes

>

## My Notes

""",
    "guide": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: note
summary: ""
created: {{ created }}
---

# {{ title }}

## Prerequisites

- [[]]

## Steps

### 1.

### 2.

### 3.

## Pitfalls

-

## See Also

- [[]]
""",
    "comparison": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: note
summary: ""
created: {{ created }}
---

# {{ title }}

## Overview

_What are we comparing and why?_

## Comparison

| Criteria | Option A | Option B |
|----------|----------|----------|
|          |          |          |
|          |          |          |

## Verdict

## Related

- [[]]
""",
    "moc": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: moc
summary: "Map of content for {{ title }}"
created: {{ created }}
---

# {{ title }}

## Core Concepts

- [[]]

## Guides

- [[]]

## References

- [[]]

## Open Questions

-
""",
}


def get_template(name: str, templates_dir=None) -> str | None:
    """Get a template by name. Checks vault templates dir first, then built-ins."""
    if templates_dir:
        custom = templates_dir / f"{name}.md"
        if custom.exists():
            return custom.read_text(encoding="utf-8")
    return BUILTIN_TEMPLATES.get(name)


def list_templates(templates_dir=None) -> list[dict]:
    """List available templates."""
    templates = []
    for name in BUILTIN_TEMPLATES:
        templates.append({"name": name, "source": "builtin"})

    if templates_dir and templates_dir.exists():
        for f in sorted(templates_dir.glob("*.md")):
            name = f.stem
            if name not in BUILTIN_TEMPLATES:
                templates.append({"name": name, "source": "custom"})
    return templates


def render_template(
    template_str: str, title: str, note_id: str, tags: list[str]
) -> tuple[dict, str]:
    """Fill a template in. Returns (its frontmatter, parsed, and its body).

    The body is filled in as text. The frontmatter is parsed with a bare
    word standing in for each placeholder, and the values go into the parsed
    data: substituted as text, a title with a `"` or a tag like `#ai` made
    the YAML invalid, and the note was written where sync could not read it.
    A `{{ tags }}` list item becomes the tags themselves.

    Raises ValueError when the template's frontmatter is not a YAML mapping.
    """
    import uuid
    from datetime import datetime

    import yaml

    from hyperresearch.core.frontmatter import FRONTMATTER_RE

    values = {
        "{{ title }}": title,
        "{{ id }}": note_id,
        "{{ tags }}": ", ".join(tags),
        "{{ created }}": datetime.now(UTC).isoformat(),
    }

    def fill(text: str) -> str:
        for placeholder, value in values.items():
            text = text.replace(placeholder, value)
        return text

    match = FRONTMATTER_RE.match(template_str)
    if not match:
        return {}, fill(template_str)

    # A bare alphanumeric word reads as a plain string wherever a placeholder
    # can stand: quoted, unquoted or inside a flow list.
    nonce = uuid.uuid4().hex
    tokens = {placeholder: f"hrtpl{nonce}{i}" for i, placeholder in enumerate(values)}
    tags_token = tokens["{{ tags }}"]
    yaml_str = match.group(1)
    for placeholder, token in tokens.items():
        yaml_str = yaml_str.replace(placeholder, token)
    try:
        data = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"frontmatter is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a YAML mapping")

    def put(value):
        if isinstance(value, str):
            for placeholder, token in tokens.items():
                value = value.replace(token, values[placeholder])
            return value
        if isinstance(value, list):
            out = []
            for item in value:
                if item == tags_token:
                    out.extend(tags)
                else:
                    out.append(put(item))
            return out
        if isinstance(value, dict):
            return {k: put(v) for k, v in value.items()}
        return value

    return {k: put(v) for k, v in data.items()}, fill(template_str[match.end():])
