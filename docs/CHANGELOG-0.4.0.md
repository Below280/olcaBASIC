# olcaBASIC 0.4.0

olcaBASIC no longer needs `b280-olca-mcp`. The engine that talks to openLCA now lives in olcaBASIC, and the MCP server (from 2.0.0) depends on olcaBASIC instead of the other way round. Installing olcaBASIC brings in `olca-ipc` and nothing else.

Requires Python 3.11 or later (`olca-ipc` 2.4 does).

## Behaviour changes

Programs written for 0.3.0 keep working, except in the cases below. Each one used to pass quietly and now stops with an error that says what to type.

| Change | 0.3.0 | 0.4.0 | What to do |
|---|---|---|---|
| A `USE PROCESS` name that matches several processes | Warning; the first match was used | Error listing the location and UUID of each candidate | Add `LOCATION "code"` to the line, or `PROVIDER "uuid"` |
| Unknown database family | Building went ahead with ecoinvent flow property names | `MAKE FLOW`, `BRIDGE` and anything else that creates a flow is refused | `DATABASE FAMILY "ecoinvent"` or `DATABASE FAMILY "flcac"` |
| Calculating a system that failed `VALIDATE` | Allowed | Refused for the rest of the session, until `VALIDATE` passes | Fix the links, or `DELETE SYSTEM` and `SYSTEM` again, then `VALIDATE` |
| Impact method names | Part of a name was enough if only one method matched (`USING "IPCC"`) | The full name is required; a near miss lists the close matches | Use the full name, for example `USING "IPCC 2021"`. `FIND METHOD "IPCC"` lists them |
| `SENSITIVITY` without `BY` | Varied by 20% | Parse error | Say the range: `BY 10%` |
| `SENSITIVITY` with nothing to vary | Ran and reported no matching parameters | Parse error | Add a `VARY` line or `FROM "file.csv"` |
| `ALLOCATE` with an unknown word | Reached openLCA and failed there | Parse error listing the valid words | `AS_DEFINED`, `PHYSICAL`, `ECONOMIC`, `CAUSAL` or `NONE` |
| `BRIDGE "Cement", kg` | Bridge named `Cement` | Bridge named `BRIDGE \| Cement \| kg` | Nothing. A bridge that already exists under the plain name is reused |
| `DELETE FLOW` | Refused by the parser | Allowed, after checking that nothing uses the flow | Nothing |
| `SAVE "file.baslca"` | Wrote the latest results as CSV into that file | Writes the programs run so far | For results use a name that does not end in `.baslca` or `.bas`, or `SAVE RESULTS` |
| `MOVE` a flow or product system | "not yet supported" | Works | Nothing |
| Errors inside `PROCESS`, `EDIT`, `SCENARIO` and `SENSITIVITY` blocks | Reported the first line of the block | Report their own line | Nothing |
| A `PROCESS` block with a wrong name on one line | Flows on earlier lines had already been created | Nothing is created: every line is looked up before anything is written | Nothing |
| Dependency | Installed `b280-olca-mcp` and `mcp` | Installs `olca-ipc` only | Nothing |

## New in 0.4.0

**Session.** Run olcaBASIC from Python and get structured results back:

```python
from olcabasic import Session

s = Session(port=8080)          # or Session(offline=True)
r = s.run('CALCULATE "Concrete block" USING "EF v3.1"')
r.ok          # True or False
r.text        # what the terminal would have shown
r.data        # the results as dictionaries
r.errors      # [{"line": ..., "message": ..., "hint": ...}]
r.warnings    # [{"line": ..., "message": ..., "level": "warning" or "note"}]
```

Variables, folders, scenarios and the latest results persist between `run` calls. `run` holds a lock from start to finish, so two programs can never write to openLCA at once. `s.run(code, dry_run=True)` parses a program and checks what can be checked without openLCA.

**Every error has a line and a hint.** The hint says what to type instead.

**Rules that used to be advice are now enforced.** See the table above: ambiguous names, the database family, validation before calculation, full method names. `CHECK ... TIER 1` always ends by saying that it checked structure only. Every default the interpreter applies (allocation, linking, `TOP`, `RUNS` and so on) is stated in the output the first time it is used in a session.

**One command reference.** `HELP`, `HELP <topic>` and `HELP <command>` (for example `HELP MAKE PROCESS`) are generated from one registry, as is the reference section of the README. The old help text, which still described `INPUT NEW`, is gone.

**Three dialects, side by side.** Navigation has an Acorn form and a Linux form for every command, and `HELP` shows both:

| Acorn | Linux | |
|---|---|---|
| `CAT` | `LS` | List the current folder |
| `DIR "folder"` | `CD "folder"` | Go to a folder |
| `UP` | `CD ..` | Up one folder |
| `BACK` | `CD -` | Back to the previous folder (new) |
| `DIR "/"` | `CD /` | To the top level (new) |
| `CDIR "name"` | | Create a folder and go into it |
| | `MKDIR "name"` | Create a folder and stay where you are (new) |
| | `PWD` | Show where you are |

**New commands.**

- `FIND SYSTEM "text"`, alongside `FIND PROCESS`, `FIND FLOW`, `FIND METHOD` and `FIND UNIT`. `FIND PROCESS` now shows each process's location, and `AT "GB"` filters by it.
- `SHOW SYSTEM "name"`, `SHOW SYSTEM "name" PARAMS`, `SHOW SYSTEM "name" LINKS "text"`, `SHOW GLOBAL PARAMS "text"`, `SHOW PROCESS "name" QUALITY`.
- `SHOW FLOW "name" USAGE [LIMIT n]`: where a flow is used.
- `DELETE FLOW "name"`: deletes a flow once every process has been read and none uses it. A flow used by a process, an impact category, a stored EPD or a stored result is refused, and the error names what uses it.
- `MOVE FLOW` and `MOVE SYSTEM`.
- `EDIT PROCESS`: when a flow appears more than once in a process, `REMOVE INPUT "name" INDEX 2` (or `PROVIDER`, `LOCATION`, `AMOUNT`) removes one of them, and `UPDATE INPUT "name" INDEX 2, ...` updates one.
- `SAVE PROGRAM "file.baslca"`: writes out every program that has run without error in the session, as the record of the work.
- `MAX(a, b)` works (it was a reserved word and could not be called).

## Fixed

- A note is printed when a `PROCESS` block uses a background process directly instead of through a bridge.
- A failed product system creation that left a system behind now says so and names the commands to inspect or remove it.
