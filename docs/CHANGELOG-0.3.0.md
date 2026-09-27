# olcaBASIC 0.3.0

Requires b280-olca-mcp 1.16.0 or later.

0.3.0 merges two lines of work that both started from 0.1.5: the 0.2.x fixes (tested live on 25/09/2026) and a second branch that added new commands. The merge was done file by file against 0.1.5 as the common ancestor.

## New in 0.3.0

**MAKE and USE.** A clearer way to write exchanges, where every line says what it is working with:

```basic
MAKE PROCESS "Concrete block; at plant"
  OUTPUT MAKE FLOW "Concrete block", 1, m3, PRODUCT
  INPUT USE PROCESS "Portland cement; at plant", 300, kg
  INPUT USE FLOW "Water, deionised", 50, kg
END PROCESS
```

`USE PROCESS` must match a process, because the point is to link a provider. `USE FLOW` links a flow directly and leaves the provider to openLCA's linking when the system is built. `MAKE FLOW` creates a new flow.

`MAKE` and `USE` are now the documented syntax. `INPUT NEW` and `OUTPUT NEW` are deprecated: they still work, with a note (shown once per session) pointing to `MAKE FLOW`, and will be removed in a future version. A bare `INPUT "name"` stays as shorthand, trying a process first and then a flow.

**EDIT PROCESS** changes an existing process in place:

```basic
EDIT PROCESS "Test wall; at site"
  ADD INPUT USE PROCESS "Construction sand and gravel; at mine", 10, kg
  REMOVE INPUT "Water, deionised"
  UPDATE INPUT "Portland cement; at plant", cement_mass * 0.06, kg
  UPDATE INPUT "Portland cement; at plant" LOCATION "US"
  ADD PARAM curing_days = 28
  SET DESCRIPTION "Updated mix"
END EDIT
```

`ADD` takes the same exchange lines as a PROCESS block. `REMOVE` and `UPDATE` name an exchange by its flow or by the process supplying it, and say INPUT or OUTPUT when a name could mean either. `UPDATE ... LOCATION` relinks to the same product from another location. Variables stay live as formulas. The reference product can't be removed, and a name that isn't in the process gives an error listing the exchanges that are. Product systems already built on the process keep their old links, so EDIT reminds you to rebuild them after adding, removing or relinking.

**EDIT FLOW** adds or updates a flow's properties, or changes its reference property:

```basic
EDIT FLOW "Concrete block"
  ADD PROPERTY "Mass" AS 2400 kg PER m3
  UPDATE PROPERTY "Mass" AS 2350 kg PER m3
  SET REFERENCE "Mass"
END EDIT
```

A property is written as a relation between units, so there's no conversion factor to get the wrong way round: `AS 2400 kg PER m3`, `AS 1 m3 PER 2400 kg` and `AS 0.4167 l PER kg` all mean the same thing. olcaBASIC works out openLCA's factor. Changing the reference rescales every factor, so exchanges keep their meaning and results don't change. Properties can't be removed here, because exchanges that use one would break and IPC can't tell where a flow is used; remove them in openLCA's flow editor. Editing a flow outside your build folders prints a note, because the change affects every model that uses it.

**UPDATE PARAMETER** writes a global parameter to the database straight away: `UPDATE PARAMETER cement_mass = 280`. A `LET` only writes it when a PROCESS, LINK or EDIT next uses it. Derived parameters can be updated with a new formula.

**SHOW** inspects what's in the database: `SHOW PROCESS "name" INPUTS`, `OUTPUTS`, `LOCATION`, `DESCRIPTION` or `PARAMS`, `SHOW FLOW "name" UNITS`, and `SHOW PARAMETER "name"`.

**LINK** adds a supplying process to an existing one: `LINK PROCESS "A" TO PROCESS "B" WITH 1000, kg`. Amounts that use variables stay live as formulas, so scenarios reach them.

**TREE** draws a multi-level contribution tree for one impact category, following the supply chain down with openLCA's upstream tree. Each branch shows its share of the result and the pedigree scores on the exchange linking it to its parent, in the foreground and the background alike. Scores of 4 or 5 are flagged by indicator name, and so are links with no scores. A summary gives the share of the result that passes through at least one weak link, per indicator, counting each branch once:

```
TREE "Test wall; at site" USING "IPCC" CATEGORY "AR6-100" LEVELS 3 TOP 5
```

`NOQUALITY` hides the scores, and `ALLOCATE` works as it does for CALCULATE. Where a background dataset is aggregated, its branch ends there.

**PEDIGREE and COMMENT** on exchange lines, both optional:

```basic
INPUT USE PROCESS "Portland cement; at plant", 300, kg PEDIGREE (1,2,4,1,3) COMMENT "Supplier EPD"
```

Scores are written as openLCA's own data quality entries, so they also appear in the openLCA desktop app. They must be whole numbers from 1 to 5, one per indicator of the process's `FLOW SCHEMA`, and a process with scored lines must have one. `PRINT DQ SYSTEMS` lists the systems in the database. `EDIT PROCESS ... UPDATE INPUT "name" PEDIGREE (...) COMMENT "..."` changes them later.

**MOVE** moves a process to another folder.

**NAVIGATE** switches which tree `CAT`, `DIR`, `UP` and `BACK` browse (processes, flows, methods or systems), each keeping its own position.

**Browsing and building are separate.** `DIR`, `UP`, `BACK` and `NAVIGATE` only change what you're looking at. New processes and flows go where `SET PROCESS FOLDER`, `SET FLOW FOLDER` or `CDIR` put them: `CDIR` creates a folder, moves into it and makes it the build folder for that tree. `PWD` shows both. Before this, browsing moved the build folder, and the live test showed that navigating the flow tree could have put new product flows inside `Elementary flows`.

**DELETE FLOW is removed.** The live test showed that openLCA deletes a flow through IPC even while a process uses it, leaving that process pointing at a flow that no longer exists. openLCA's IPC server has no way to ask where a flow is used (the desktop Usage view runs inside openLCA), and scanning every process was too slow to be practical. So olcaBASIC no longer deletes flows: `DELETE FLOW` gives an error explaining why, and flows are deleted in openLCA, which checks first. We've asked GreenDelta to expose their usage search over IPC ([olca-modules issue #76](https://github.com/GreenDelta/olca-modules/issues/76)); if they do, `DELETE FLOW` can come back safely. `MAKE FLOW` reuses a flow with the same name in the same folder, so re-running a program doesn't create duplicates.

**Tab completion** in the REPL for commands, sub-commands, folder names and database names. It needs `pyreadline3` on Windows: `pip install olcabasic[completion]`.

**FIND PROCESS** now shows each process's UUID, which is what `PROVIDER`, `LINK` and `MOVE` take when several processes share a name.

## How the overlap was resolved

The second branch fixed five of the same problems 0.2 fixed: elementary flows, typo protection, ambiguity warnings, flow search by category, and `LOCATION`. In each case the 0.2 version was kept, because it had been tested live:

- The branch searched only ecoinvent-style compartments ('emission to air'), which fails on FLCAC, and fell back to the whole database when a category matched nothing. 0.2 handles both naming styles and never leaves the compartment.
- The branch's `LOCATION` fell back to a substring match and kept every candidate when nothing matched. 0.2 matches exactly and lists the available codes.

`DIR` combines both: it acts on the active tree (from the branch) and refuses folders that don't exist (from 0.2).

## Fixed during the merge

- `SHOW PARAMETER`, as documented in the branch's changelog, couldn't be parsed, because the parser only accepted `PARAMS` or `GLOBAL`.
- `USE PROCESS` and `USE FLOW` were parsed but ignored, so both behaved like a bare `INPUT`. They now do what they say.
- `LINK` froze variable amounts into numbers, so scenarios couldn't reach them. It now passes them as formulas and creates the global parameters they use.
- `LINK`, `MOVE`, `SHOW PROCESS`, `PRINT DETAILS` and `BRIDGE ... PROVIDER` picked the first process with a matching name. They now require a unique name or a UUID, and list the locations when a name is shared.
- `TO` or `FROM` followed by something other than a compartment silently made a product flow. It's now an error.
- `TREE ... LEVELS x` crashed on a non-number. It's now a normal error.
- `SHOW PARAMETER` shows a formula parameter as its formula and current value (openLCA stores 0 as the value), and matches the name exactly before falling back to part of it.
- `LEVELS` and `OUTPUTS` are not reserved words, so they can be used as variable names. `CATEGORY` and `VALUE` are reserved.
- In the REPL, a one-line `MAKE FLOW` waited for an `END`. `MAKE` now opens a block only for `MAKE PROCESS`.
- The typo error suggests `INPUT MAKE FLOW`.

## Unchanged from 0.2.1

Strict parsing, global and formula parameters, DELETE by name, rebuild warnings, both compartment naming styles, and every other 0.2 fix. The offline tests from 0.2.1 give identical results on 0.3.0, apart from the updated typo message.

## Known rough edges

- `MOVE` handles processes only.
- `DELETE PROCESS` and `DELETE SYSTEM` don't check whether other processes or systems refer to them, because IPC can't tell olcaBASIC that either. Use them on your own models.
- EDIT can't remove one exchange of a flow that appears more than once in the same process.
- EDIT's REMOVE leaves behind the parameter the MCP created for a plain-number amount. It's harmless.
- Pedigree scores inform TREE. They are not converted to uncertainty distributions.

## Testing

All offline tests pass. `test_features.baslca` now uses `MAKE`/`USE` throughout and also exercises `NAVIGATE`, `LINK` (with a variable amount), `EDIT PROCESS` (update, add and remove), `SHOW`, a three-level `TREE` with pedigree, `PEDIGREE` and `COMMENT` on a line, `EDIT FLOW` (checking the result is unchanged after a reference change), `UPDATE PARAMETER` (checking it matches the Low cement scenario) and `MOVE`. It no longer deletes flows. The linked sand scales with `cement_mass`, so the Low and High scenarios must still come out at exactly 2/3 and 4/3 of Baseline. The first live run of 0.3.0 confirmed LINK, EDIT, MOVE, SHOW and the exact scenario ratios, and found the DELETE FLOW problem, the browse/build trap and the empty TREE, all dealt with above. The new TREE and PEDIGREE haven't been run live yet.
