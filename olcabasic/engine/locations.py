"""Finding a location by its code, name or UUID.

openLCA's descriptors of locations carry no code, and a full location
carries its geometry (all of ecoinvent's locations together are about
180 MB, ten seconds over IPC), so the code cannot be read cheaply. But
openLCA gives a location from its reference data the UUID of its
lower-case code (KeyGen: a name-based UUID, version 3, as Java's
UUID.nameUUIDFromBytes makes it), so 'GB' is found by working out that
UUID. Checked on openLCA 2.7.0 with ecoinvent's locations, 14/11/2026.
"""

import hashlib
import uuid
from typing import List, Optional, Tuple


def key_of(code: str) -> str:
    """The UUID openLCA's KeyGen gives the text."""
    digest = bytearray(hashlib.md5(code.encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def find(descriptors: List, text: str) -> Tuple[Optional[object], Optional[str]]:
    """(descriptor, None) or (None, why not). By UUID, code (also a code
    the descriptor carries, as some servers send), exact name, then a
    part of a name that fits one location only."""
    want = (text or "").strip()
    low = want.lower()
    if not want:
        return None, "No location was given."
    by_id = {d.id: d for d in descriptors}
    if want in by_id:
        return by_id[want], None
    hit = by_id.get(key_of(low))
    if hit is not None:
        return hit, None
    for d in descriptors:
        if (getattr(d, "code", "") or "").lower() == low \
                or (d.name or "").lower() == low:
            return d, None
    part = [d for d in descriptors if low in (d.name or "").lower()]
    if len(part) == 1:
        return part[0], None
    if part:
        shown = "; ".join(sorted(d.name or "" for d in part[:6]))
        return None, (f"Location '{want}' fits {len(part)} locations by "
                      f"name: {shown}. Give the code or the whole name.")
    return None, (f"No location has the code, name or UUID '{want}'. "
                  f"FIND LOCATION \"{want}\" searches the names.")
