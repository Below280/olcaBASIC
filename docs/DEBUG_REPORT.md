# olcaBASIC debug report

Patch set against olcaBASIC v0.1.5 plus the resolution fixes from 25/09/2026, and a matching b280-olca-mcp release.

olcaBASIC files changed: `tokeniser.py`, `parser.py`, `interpreter.py`, `bridge.py`, `repl.py`, `runtime.py`, `__init__.py` and `pyproject.toml` (now 0.2.0, requiring `b280-olca-mcp>=1.15.0`). Use your uploaded `ast_nodes.py` as is (it already has the `location` field).

b280-olca-mcp files changed: `functions.py`, `server.py`, `__init__.py`, `server.json`, `README.md` and `docs/tools.md` (now 1.15.0). Release the MCP first, since olcaBASIC 0.2.0 depends on it.

All testing was offline: the parser and tokeniser directly, the interpreter against a fake openLCA with ecoinvent-style duplicate names and compartments, and the MCP's scenario, sensitivity and global parameter functions against a fake IPC client. Nothing here has been run against a live IPC server yet, so a smoke test on a real database is the next step (see the end).

Because the parser is now strict, programs that used to run with silently ignored text will now stop with an error. That is the point, but it is a behaviour change, so 0.2.0 is a better version number than 0.1.6.

## The common thread

Most of what I found was one pattern: text the interpreter didn't understand was skipped without a word. The parser's `expect_newline` never complained about leftover tokens, unknown statements were stepped over one token at a time, and the tokeniser dropped characters it didn't recognise. For an LCA tool that is the worst failure mode, because the model still builds and calculates, just without the bit you typed. The fix is the same everywhere: anything not understood is now an error with the line number and a hint.

## Bugs fixed

### Silent data loss

**A mistyped line inside PROCESS vanished.** `INPT "cement", 300, kg` was skipped, so the process was created without that input. Unknown lines inside PROCESS, SCENARIO, SENSITIVITY, SYSTEM, BRIDGE, RUN SCENARIOS and EDIT blocks now raise an error naming what's allowed.

**`RUN SCENARIOS` followed by `SAVE RESULTS` ate the rest of the program.** The parser took `SAVE` as the start of a RUN SCENARIOS block, read `RESULTS` as the filename, then consumed every statement up to the next `END`, silently. Block form is now only recognised for `FROM`, `SAVE "file"` or `END RUN`.

**`SYSTEM`, `RUN SCENARIOS` or `BRIDGE` as the last line of an IF, FOR or SUB stole its `END`.** A bare `END` was treated as closing the SYSTEM block. They now only claim `END SYSTEM`, `END RUN` or `END BRIDGE`.

**`LET r = .45` gave 45.** The leading dot was dropped. Numbers like `.45` now parse.

**`2^3` gave 2.** `^` was an unknown character, so it was skipped and the 3 was lost. `^` is now a proper power operator (right-associative, binds tighter than unary minus, so `-2^2` is -4 as in BASIC), and it passes through to openLCA formulas.

**Line continuation lost the continued line.** `PRINT "a", _` followed by `"b"` produced `a` and an identifier called `_`. The trailing underscore is now stripped before the next line is joined.

**`VARY a, b` only varied `a`.** Several names on one VARY line now work.

**`CONFIRM DELETE OFF` turned delete prompts off.** `OFF` wasn't a keyword, so the statement defaulted to ON, which skips the confirmation prompt. The opposite of what was asked, on a destructive command.

**A typo in a variable name became a string.** An undefined name evaluated to its own text, so `cemnt_mass * 2` gave `cemnt_masscemnt_mass`. Undefined names are now an error suggesting quotes if a name was meant.

**`INCLUDE` of a missing file was ignored.** It became a REM comment and the program carried on without it. It is now an error, and an include loop is caught instead of recursing until Python gives up.

**`READ INPUTS FROM DATA` doubled up in loops.** It appended to the parsed statement itself, so a PROCESS run twice gained the DATA exchanges twice. It now works on a copy.

**`SAVE RESULTS` wrote empty files.** For contribution, inventory and Monte Carlo results the CSV writer returned nothing, and the file was written and reported as saved. It now says those result types aren't supported yet. The file is also opened with `newline=""`, which stops the blank row between every line that Excel shows on Windows.

### Resolution (the original issue)

**Elementary flows could land in the wrong compartment.** If the category prefix didn't match the database's naming, the search fell back to every flow, so `TO AIR` could pick the water-compartment flow. Elementary searches are now strict: they stay inside the compartment and error if nothing matches.

**`FROM NATURE` only searched `resource/in ground`.** It now covers every resource sub-compartment (`Elementary flows/resource`), so well water, land and biotic resources are found.

**Sub-compartment choice.** With several exact matches in a compartment, `unspecified` is preferred, and a note says which one was used.

**Background flows went missing once the project folder had flows in it.** The product search was confined to the folder whenever the folder was non-empty. It now prefers the folder and falls back to the whole database.

**`LOCATION` fell back silently.** A code that matched nothing kept every candidate and took the first. It now errors and lists the codes that exist ('Available: CH, GLO, RoW'). Matching is exact, so `CA` no longer catches `CA-QC`. If openLCA returns no location codes at all, the error says so rather than pretending to filter.

**`PROVIDER` by a duplicated name picked the first, or dropped the provider.** An explicit PROVIDER now has to identify one process (UUID or unique name). If the name is shared, the error lists the locations and points to LOCATION. Previously, if PROVIDER failed to resolve, the automatically found provider was thrown away too.

**Global variables were attached to processes by substring.** A variable called `mass` was added as a parameter to any process whose formula mentioned `cement_mass`. It's now a whole-word match.

### Language features that didn't work

**Numeric FOR loops always failed.** `FOR i = 1 TO 3` raised 'Expected EQUALS' because the parser looked for `=` as a keyword. Fixed. The loop now counts iterations up front, so `STEP 0.1` doesn't drift, and whole-number loops give `1, 2, 3` rather than `1.0, 2.0, 3.0`.

**`NEXT m` after `FOR EACH m` ran a SUB called `m`.** The loop variable after NEXT is now accepted.

**Local `LET` inside PROCESS couldn't be used in exchanges.** The values weren't visible when the amounts were evaluated, so `INPUT "x", cement_mass * ratio, kg` with a local `ratio` failed. Local LETs are now evaluated into a temporary scope first. Non-numeric local parameters are an error instead of silently becoming 0.

**Sub-keywords that were never keywords.** `FIND METHOD`, `FIND UNIT`, `FIND ... AT`, `VALIDATE ... WITH CALCULATION`, and in EDIT `PARAM`, `EXCHANGE`, `AMOUNT` and `CATEGORY` all looked for keywords that didn't exist, so they misparsed or did nothing. They're now matched as words, which also means they don't become reserved and can still be used as variable names.

**Single-line IF.** `IF x > 3 THEN PRINT "big" ELSE PRINT "small"` now works. The REPL already sent these straight to the interpreter, which then failed looking for END IF.

**`x = 5` without LET.** Now accepted as an implicit LET, as in most BASICs.

**`SET FLOW FOLDER` was ignored by PROCESS.** New foreground flows went into the process folder, contrary to the README example. They now go into the flow folder when one is set.

**`INT(-2.5)` gave -2.** BASIC's INT floors, so it now gives -3.

### Startup and REPL

**'Connected' when openLCA wasn't running.** Creating the IPC client doesn't open a connection, so `connect()` always succeeded and the banner showed 'Database: ? processes'. It now makes one real request and falls back to offline mode with the instructions if that fails. This is the first thing every new user who forgets the IPC server would have hit.

**Ctrl+C during a long calculation killed the REPL with a traceback.** It now stops the command and returns to the prompt.

### Clear errors instead of silent skips

`GOTO`, `GOSUB`, `RETURN`, `ON ERROR`, `LOAD`, `HISTORY`, `INSPECT`, `LIST` and standalone `NEW` are reserved words with no implementation. They now say 'not supported' rather than being skipped. Line numbers, `&`, `:` and `;` get errors with a hint ('use + to join strings' and so on). Unterminated strings and missing `)` are errors. Reserved words used as variable names (`LET water = 5`) get a message suggesting an alternative. `EDIT PROCESS` now errors with 'not implemented, nothing was changed' instead of printing 'Editing process'.

## Parameters (fixed across both packages)

These were the two issues that gave wrong scenario results without any warning.

**Shared parameters.** In the MCP, `run_scenarios` and `run_sensitivity` built a name-to-parameter lookup with a dict, so when a name existed in several processes only the last copy survived, and a scenario changed one process but not the others. Both now collect every copy through a new `_parameter_targets` helper and redefine all of them. Sensitivity moves each copy by the same percentage from its own baseline. The CSV scenario and sensitivity tools call these two functions, so four tools are fixed. Results now report `shared_parameters` when a name was redefined in more than one place. Global parameters are looked up from the database if openLCA doesn't return them with the system, so a global used in any formula can always be redefined.

**Formula parameters.** The MCP gains a `create_global_parameter` tool (a value for an input parameter, or a formula for a dependent one), and `create_process` now accepts `formula` on process parameters. Trying to set a formula parameter in a scenario or sensitivity run is reported under `dependent` with a warning, instead of being passed to openLCA to do nothing.

**How olcaBASIC uses this.** A top-level `LET` used in an exchange now becomes one openLCA global parameter, instead of a separate copy on every process that uses it. A `LET` defined from other variables (`LET water_mass = cement_mass * water_ratio`) becomes a global formula parameter, with its inputs created first. So a scenario that changes `cement_mass` now changes `water_mass` too, and every process that uses either. The README's Parameters section is now accurate as written. `LET` inside a PROCESS block stays process-scope and takes precedence inside that process, which gives a clean rule: top level means model-wide, inside PROCESS means local. Setting a derived variable in a SCENARIO or VARY stops with an error naming the inputs to change instead. Circular definitions are caught. olcaBASIC only writes a global when its value or formula has changed since the last write in the session.

Two consequences are worth knowing about, and both belong in the article.

- Global parameters are database-wide. If a database already has a global called `cement_mass` from another model, olcaBASIC updates it and prints a NOTE with the old value, because that other model will change too. The MCP returns `already_existed`, `previous` and `changed`, so this is always detectable.
- Because the parameter is shared, a later `LET cement_mass = 250` followed by another PROCESS updates the value used by processes built earlier in the program. The last value written is the baseline, and scenarios are the way to compare values.

## Known issues not fixed

These need design decisions rather than patches.

**Models built with 0.1.x** have process-scope copies of their variables. Those copies shadow any global of the same name inside their process, so rebuild old models rather than mixing versions.

**Browsing moves your build folder.** `DIR`, `UP`, `BACK` and `CAT` all work on the process folder. Browse into `31-33: Manufacturing` to look around, then write a PROCESS, and it's created inside the background database's category tree. A separate browse location, with `SET PROCESS FOLDER` or `CDIR` as the only things that set the build folder, would avoid this. It changes how the navigation feels, so it's your call.

**Functions in exchange and parameter formulas.** `INPUT "x", SQR(a), kg`, or a derived `LET` that uses a function, passes `SQR(a)` to openLCA as text. openLCA's formula functions have their own names, and I haven't checked which of the BASIC built-ins match, so these may fail at process creation.

**EDIT PROCESS** parses but isn't implemented.

**Error line numbers inside blocks** point to the start of the block, not the offending INPUT or OUTPUT line, because exchanges don't carry their own line numbers.

**`SAVE "file"` without RESULTS** saves results, not the program.

**SUBs can't change global variables.** A LET inside a SUB creates a local. That may be what you want, but it isn't documented.

## 0.2.1: live test and fixes

The live smoke test ran on 25/09/2026 against openLCA 2.x with the FLCAC (USLCI) database, using the rewritten `test_features.baslca`. The first run showed that it had been reusing a model from an earlier run, which led to four more fixes. After those, every check passed exactly.

### What the live test found

**DELETE by name never worked.** The MCP deletes by UUID, but olcaBASIC passed the name, got 'not found' and printed 'may already be deleted'. So cleanup never removed anything, and later runs picked up the old model. olcaBASIC now resolves the name to an ID before asking for confirmation, and refuses if several entities share the name.

**Existing processes and systems were reused without warning.** The MCP returns an existing process or system when the name and category match, and applies none of the new definition. That was reported as 'exists', so editing a PROCESS block and re-running changed nothing. It is now a WARNING saying the changes were not applied, with the DELETE command to rebuild.

**DIR invented folders.** The old test file navigated to `3273: Cement and Co`, a name cut short by the 40-character FIND output. 0.1.5's prefix matching happened to accept it. 0.2.0 rejected it as an absolute path, then built a relative path that didn't exist, and CDIR created a model inside it. DIR now errors on a folder that doesn't exist. Tables mark cut-off cells with '...', and the process search shows up to 70 characters.

**FLCAC names compartments differently.** It uses `Elementary flows/emission/air`, with `ground` for soil and no `unspecified` sub-compartment. The prefixes coded in 0.2.0 were ecoinvent-style (`emission to air`), so `TO AIR` would have failed on FLCAC. Each direction now accepts both forms. When a flow exists in several sub-compartments, the default is `unspecified`, then the compartment root, then the shortest path.

**A false 'changed' note for formula parameters.** MCP 1.15.0 compares the value openLCA stores on a formula parameter with `None`, so an identical formula was reported as changed. olcaBASIC now makes that comparison itself. The MCP fix is in 1.15.1, which can be released separately.

Smaller changes: `FIND FLOW` prints a table with type, unit and full category instead of 'flows: [20 items]'. Sensitivity percentages below 1% show two decimals, so small effects no longer appear as 0.0%. Floats print as `800.1` rather than `800.0999999999999`.

### Test model and results

The test builds a concrete process and a wall process. `cement_mass` (300) is used in both, `sand_mass` is defined as `cement_mass * aggregate_ratio`, and the concrete emits `cement_mass * 0.001` kg of CO2 to air. Because every input scales with `cement_mass`, a scenario that reaches all of them must scale the result by exactly the scenario ratio.

| Check | Expected | Result (IPCC AR4-100, kg CO2 eq) |
|---|---|---|
| Baseline | | 99.896818 |
| Low cement (200) | Baseline × 2/3 = 66.597879 | 66.597879 |
| High cement (400) | Baseline × 4/3 = 133.195758 | 133.195758 |
| CO2 to air characterised | +0.060000 on the run without it (99.836818) | +0.060000 in every category |
| Sensitivity, `cement_mass` ±10% | ±10.0% | ±10.0% |
| Sensitivity, `aggregate_ratio` ±10% | Small, non-zero | ±0.04% |

The exact ratios confirm three things at once: a scenario changes a shared global parameter in every process, openLCA recalculates formula parameters from redefined inputs, and the elementary flow lands in the right compartment and is characterised. The clean start and cleanup deleted everything by name, and every entity was freshly created.

### Still to test live

`LOCATION` needs a database with duplicate process names, such as ecoinvent. `MONTECARLO`, `CONTRIBUTION`, `INVENTORY`, `BRIDGE` and `INCLUDE` weren't part of this run.

## Original smoke test plan

Worth running on ecoinvent and on USLCI before the article goes out:

1. Start without the IPC server running and check it falls back to offline mode cleanly.
2. `FIND PROCESS "market for cement"` and check the location column is populated. If it's empty, LOCATION can't work and the error will say so.
3. A PROCESS with `INPUT "market for cement, Portland", 300, kg LOCATION "RoW"`, then the same with `LOCATION "UK"` to see the available-codes error.
4. `OUTPUT "Carbon dioxide, fossil", 5, kg TO AIR` and `INPUT "Water, well, in ground", 1, m3 FROM NATURE` to confirm the compartment prefixes match both databases' category naming.
5. The parameter chain: define `cement_mass`, `water_ratio` and `water_mass = cement_mass * water_ratio`, use `cement_mass` in two processes and `water_mass` in one, then run a scenario that changes `cement_mass`. Check that both processes and the water input all move. This confirms openLCA recalculates dependent global parameters from redefined inputs at calculation time, which is how the openLCA formula interpreter is meant to work but hasn't been tested here.
6. Check `system_parameters` output on that system to see whether openLCA returns global parameters with the system. The MCP copes either way, but it's worth knowing.
7. `test_features.baslca`, which still parses to the same 47 statements.
