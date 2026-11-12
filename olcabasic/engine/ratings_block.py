"""
The data quality ratings of a process, kept in its description.

openLCA keeps 255 characters of tags for a process, which the reasons
of three ratings overrun (and a save that overruns is refused whole).
So the ratings are written as a block at the end of the description,
where openLCA shows them to anyone who opens the process:

    Data quality ratings (olcaBASIC):
    Geography: Good. Same market as the supply
    Technology: Good. Same process route
    Time: Fair. Data from 2019

The rest of the engine sees them as the keys rating_geography,
rating_technology, rating_time and the same with _reason, exactly as
if they were tags. A reason is held in those keys with its commas
written %2C (and % as %25), as tags need; the description has it plain.
"""

from typing import Dict, Optional

MARKER = "Data quality ratings (olcaBASIC):"
ASPECTS = (("rating_geography", "Geography"),
           ("rating_technology", "Technology"),
           ("rating_time", "Time"))
KEYS = tuple(k for k, _ in ASPECTS) + tuple(k + "_reason" for k, _ in ASPECTS)


def _plain(text: str) -> str:
    return str(text).replace("%2C", ",").replace("%25", "%")


def _coded(text: str) -> str:
    return (str(text).replace("%", "%25").replace(",", "%2C")
            .replace("\n", " ").strip())


def split(description: Optional[str]):
    """(the description without the block, the lines of the block)."""
    text = description or ""
    at = text.rfind(MARKER)
    if at < 0:
        return text, []
    return text[:at].rstrip(), text[at + len(MARKER):].strip().splitlines()


def strip(description: Optional[str]) -> str:
    return split(description)[0]


def read(description: Optional[str]) -> Dict[str, str]:
    """The ratings in a description, as tag-like keys."""
    out = {}
    labels = {label: key for key, label in ASPECTS}
    for line in split(description)[1]:
        label, sep, rest = line.partition(":")
        key = labels.get(label.strip())
        if not sep or key is None:
            continue
        level, _, reason = rest.strip().partition(". ")
        level = level.rstrip(".").strip()
        if level:
            out[key] = level
            out[key + "_reason"] = _coded(reason)
    return out


def write(description: Optional[str], ratings: Dict[str, Optional[str]]) -> str:
    """The description with the ratings set. A level of None removes
    that rating; ratings not named are kept."""
    body, _ = split(description)
    have = read(description)
    for key, value in ratings.items():
        if value is None:
            have.pop(key, None)
        else:
            have[key] = str(value)
    lines = []
    for key, label in ASPECTS:
        if have.get(key):
            reason = " ".join(_plain(have.get(key + "_reason", "")).split())
            lines.append(f"{label}: {have[key]}. {reason}".rstrip())
    if not lines:
        return body
    block = MARKER + "\n" + "\n".join(lines)
    return f"{body}\n\n{block}" if body else block


def carry(old: Optional[str], new: Optional[str]) -> str:
    """A new description that keeps the ratings of the old one."""
    return write(strip(new), read(old))
