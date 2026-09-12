"""Cheap action completion for the small model's domain anchors.

This only adds registered tools to a binding; preferences and the execution
gateway remain responsible for authorization. Discovery is still available
for paraphrases and domains with no anchor.
"""
from __future__ import annotations

import re
import unicodedata

_ACTIONS = (
    (r"\b(supprim\w*|effac\w*|corbeille|delete|remove|trash)\b", ("delete", "remove", "trash")),
    (r"\b(envoi\w*|enver\w*|send)\b", ("send",)),
    (r"\b(repond\w*|reponse|reply)\b", ("reply",)),
    (r"\b(cre\w*|ajout\w*|create|add)\b", ("create", "add")),
    (r"\b(modifi\w*|chang\w*|deplac\w*|move|update|edit)\b", ("update", "move")),
    (r"\b(lis|lire|lecture|resum\w*|read|summari\w*)\b", ("read", "get")),
    (r"\b(marque\w*|lus?|unread|mark)\b", ("mark",)),
)


def requested_action_names(query: str, tools, anchor_names: set[str]) -> set[str]:
    normalized = "".join(c for c in unicodedata.normalize("NFKD", query.lower())
                         if not unicodedata.combining(c))
    families = {n.split("_", 1)[0] for n in anchor_names}
    verbs = {verb for pattern, names in _ACTIONS if re.search(pattern, normalized)
             for verb in names}
    names = set()
    for t in tools:
        name = getattr(t, "name", "")
        parts = name.split("_")
        if len(parts) >= 2 and parts[0] in families and parts[1] in verbs:
            # For Gmail, exact IDs are the simplest route. Broad purges and
            # raw APIs remain discoverable, not offered for every deletion.
            if parts[0] == "gmail" and "trash" in parts and name != "gmail_trash_emails":
                continue
            names.add(name)
    return names
