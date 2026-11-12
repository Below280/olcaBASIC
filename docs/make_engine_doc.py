"""Write docs/ENGINE.md from the public methods of olcabasic.engine.Engine.

    python docs/make_engine_doc.py
"""

import inspect
import re
from pathlib import Path

from olcabasic.engine import Engine

HEAD = """# The engine

`olcabasic.engine.Engine` is the layer that talks to openLCA through `olca-ipc`. The interpreter, `Session` and the MCP server all go through it. It is the class that was `b280_olca_mcp.functions.LCAFunctions` up to B280-olca-MCP 1.16 (`LCAFunctions` is kept as an alias).

```python
from olca_ipc import Client
from olcabasic.engine import Engine

engine = Engine(Client(8080))
engine.search_processes("cement", limit=5)
```

Most methods return a dictionary, and report a failure as `{"error": "..."}` and not as an exception. Names that start with an underscore are private and may change.

For most uses `olcabasic.Session` is the better entry point: it runs programs, serialises access to openLCA and applies the language's rules. The engine applies none of them: it will, for example, accept part of a method name.
"""


def first_sentence(fn) -> str:
    doc = inspect.getdoc(fn) or ""
    text = " ".join(doc.split("\n\n")[0].split())
    m = re.match(r"(.+?[.:])(\s|$)", text)
    return (m.group(1) if m else text).rstrip(":.")


def main():
    rows = []
    for name, fn in inspect.getmembers(Engine, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        sig = str(inspect.signature(fn))
        sig = sig.replace("(self, ", "(").replace("(self)", "()")
        sig = re.sub(r" -> .*$", "", sig)
        rows.append((name, sig, first_sentence(fn)))
    out = [HEAD, f"## Public methods ({len(rows)})", "",
           "This list is generated from the code: "
           "`python docs/make_engine_doc.py`.", "",
           "| Method | What it does |", "|---|---|"]
    for name, sig, text in rows:
        out.append(f"| `{name}{sig}` | {text} |".replace(
            "Optional[", "Optional[").replace(" | None", ""))
    path = Path(__file__).with_name("ENGINE.md")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(rows)} methods written to {path}")


if __name__ == "__main__":
    main()
