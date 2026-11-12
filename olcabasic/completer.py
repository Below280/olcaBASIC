"""
Tab completion for olcaBASIC REPL.

Provides context-aware completion for:
- Keywords at the start of a line
- Sub-keywords after primary keywords
- Folder names after DIR/CAT/CD
- Process, flow, and method names inside quotes
- Impact category names after CATEGORY

Degrades gracefully if readline is not available.
"""

from typing import List, Optional

# Try to import readline (Linux/Mac built-in, Windows needs pyreadline3)
try:
    import readline
    HAS_READLINE = True
except ImportError:
    try:
        import pyreadline3 as readline
        HAS_READLINE = True
    except ImportError:
        HAS_READLINE = False


# Primary keywords (start of line)
PRIMARY_KEYWORDS = [
    "BACK", "BRIDGE",
    "CAT", "CALCULATE", "CD", "CDIR", "CHECK", "CLEAR",
    "CONFIRM", "CONTRIBUTION",
    "DATA", "DELETE", "DIR",
    "EDIT", "EXIT", "EXPORT", "EXTRACT",
    "FIND", "FLOW", "FOR",
    "HELP",
    "IF", "INCLUDE", "INPUT", "INVENTORY",
    "LET", "LINK", "LOAD", "LS",
    "MAKE", "MONTECARLO", "MOVE",
    "NAVIGATE", "NEW",
    "PRINT", "PWD",
    "QUIT",
    "REFRESH", "RUN",
    "SAVE", "SCENARIO", "SENSITIVITY", "SET", "SHOW", "SYSTEM",
    "TREE",
    "UP", "UPDATE",
    "VALIDATE",
]

# Sub-keywords after specific primary keywords
SUB_KEYWORDS = {
    "MAKE": ["PROCESS", "FLOW", "BRIDGE", "SYSTEM"],
    "SHOW": ["PROCESS", "FLOW", "PARAMETER"],
    "PRINT": ["DATABASE", "PROCESSES", "METHODS", "SYSTEMS",
              "FLOWS", "PARAMS", "DETAILS", "RESULTS",
              "QUALITY", "LINKS", "UNITS"],
    "FIND": ["PROCESS", "FLOW", "METHOD", "CHEMICAL", "UNIT"],
    "DELETE": ["PROCESS", "SYSTEM"],
    "MOVE": ["PROCESS", "FLOW", "SYSTEM"],
    "NAVIGATE": ["PROCESSES", "FLOWS", "METHODS", "SYSTEMS"],
    "SET": ["PROCESS", "FLOW", "FOLDER"],
    "LINK": ["PROCESS", "FLOW"],
    "CAT": ["PROCESSES", "FLOWS", "SYSTEMS"],
    "LS": ["PROCESSES", "FLOWS", "SYSTEMS"],
    "DIR": [],
    "EDIT": ["PROCESS", "FLOW"],
    "UPDATE": ["PARAMETER"],
    "HELP": ["PROCESS", "FOLDER", "NEW", "SCENARIO",
             "SENSITIVITY", "TREE", "NAVIGATE"],
    "CONFIRM": ["DELETE"],
    "INPUT": ["USE", "MAKE", "NEW"],
    "OUTPUT": ["MAKE", "NEW"],
    "RUN": ["SCENARIOS"],
}

# Keywords after SHOW PROCESS "name"
SHOW_SUB = ["INPUTS", "OUTPUTS", "LOCATION", "DESCRIPTION",
            "PARAMS", "UNITS", "VALUE"]

# Keywords after CALCULATE/TREE
CALC_SUB = ["USING", "ALLOCATE"]
TREE_SUB = ["USING", "CATEGORY", "LEVELS", "TOP"]


class Completer:
    """Context-aware tab completer for olcaBASIC."""

    def __init__(self, bridge=None, runtime=None):
        self.bridge = bridge
        self.runtime = runtime
        self.matches = []
        self._process_cache = []
        self._flow_cache = []
        self._method_cache = []
        self._cache_loaded = False

    def setup(self):
        """Register the completer with readline."""
        if not HAS_READLINE:
            return

        readline.set_completer(self.complete)
        readline.set_completer_delims(' \t\n')
        # Handle quotes in completion
        readline.parse_and_bind("tab: complete")

    def _load_caches(self):
        """Lazy-load entity names from the database."""
        if self._cache_loaded or not self.bridge or not self.bridge.connected:
            return
        try:
            import olca_schema as o
            descs = self.bridge.get_descriptors(o.Process)
            self._process_cache = [d.name for d in descs]
            descs = self.bridge.get_descriptors(o.Flow)
            self._flow_cache = [d.name for d in descs][:500]
            methods = self.bridge.list_methods()
            self._method_cache = [
                m.get("name", "") for m in methods.get("methods", [])]
            self._cache_loaded = True
        except Exception:
            pass

    def invalidate_cache(self):
        """Clear cached names (call after REFRESH/DELETE)."""
        self._cache_loaded = False
        self._process_cache = []
        self._flow_cache = []
        self._method_cache = []

    def complete(self, text: str, state: int) -> Optional[str]:
        """readline completer callback."""
        if state == 0:
            line = readline.get_line_buffer().lstrip()
            self.matches = self._get_matches(line, text)
        if state < len(self.matches):
            return self.matches[state]
        return None

    def _get_matches(self, line: str, text: str) -> List[str]:
        """Determine context and return completions."""
        upper = line.upper().strip()
        text_upper = text.upper()

        # Inside quotes: complete entity names
        if '"' in line and line.count('"') % 2 == 1:
            # We're inside an open quote
            return self._complete_quoted(line, text)

        words = upper.split()

        # Empty line or first word: primary keywords
        if not words or (len(words) == 1 and not line.endswith(" ")):
            return [k + " " for k in PRIMARY_KEYWORDS
                    if k.startswith(text_upper)]

        first = words[0]

        # Second word: sub-keywords
        if first in SUB_KEYWORDS:
            if len(words) == 1 or (len(words) == 2 and not line.endswith(" ")):
                subs = SUB_KEYWORDS[first]
                return [s + " " for s in subs
                        if s.startswith(text_upper)]

        # After SHOW PROCESS "name": show sub-commands
        if first == "SHOW" and len(words) >= 3:
            return [s + " " for s in SHOW_SUB
                    if s.startswith(text_upper)]

        # After CALCULATE/TREE: using, category, etc.
        if first == "CALCULATE":
            return [s + " " for s in CALC_SUB
                    if s.startswith(text_upper)]

        if first == "TREE":
            return [s + " " for s in TREE_SUB
                    if s.startswith(text_upper)]

        # After USE: PROCESS or FLOW
        if "USE" in words:
            idx = words.index("USE")
            if idx == len(words) - 1 or (idx == len(words) - 2
                                          and not line.endswith(" ")):
                return [s + " " for s in ["PROCESS", "FLOW"]
                        if s.startswith(text_upper)]

        # After MAKE: FLOW, PROCESS
        if "MAKE" in words and first not in ("MAKE",):
            return [s + " " for s in ["FLOW", "PROCESS"]
                    if s.startswith(text_upper)]

        return []

    def _complete_quoted(self, line: str, text: str) -> List[str]:
        """Complete inside quotes based on command context."""
        self._load_caches()

        upper = line.upper()
        search = text.lower()

        # Determine what kind of entity to search for
        if "USING" in upper:
            # After USING: method names
            return [m for m in self._method_cache
                    if m.lower().startswith(search)][:15]

        if "CATEGORY" in upper:
            # After CATEGORY: impact category names from last results
            if self.runtime and self.runtime.last_results:
                cats = []
                impacts = self.runtime.last_results.get("impacts", [])
                for imp in impacts:
                    name = imp.get("category", "")
                    if name and name.lower().startswith(search):
                        cats.append(name)
                return cats[:15]
            return []

        if "PROCESS" in upper or "INPUT" in upper:
            # Process names
            return [p for p in self._process_cache
                    if p.lower().startswith(search)][:15]

        if "FLOW" in upper or "OUTPUT" in upper:
            # Flow names
            return [f for f in self._flow_cache
                    if f.lower().startswith(search)][:15]

        if "DIR" in upper or "CAT" in upper or "CD" in upper:
            # Folder names
            return self._complete_folders(search)

        if "METHOD" in upper:
            return [m for m in self._method_cache
                    if m.lower().startswith(search)][:15]

        # Default: try processes first
        matches = [p for p in self._process_cache
                   if p.lower().startswith(search)][:10]
        if not matches:
            matches = [f for f in self._flow_cache
                       if f.lower().startswith(search)][:10]
        return matches

    def _complete_folders(self, search: str) -> List[str]:
        """Complete folder/category names."""
        if not self.bridge or not self.bridge.connected:
            return []

        try:
            mode = self.runtime.navigation_mode if self.runtime else ""
            entity_type = {
                "PROCESSES": "PROCESSES", "FLOWS": "FLOWS",
                "METHODS": "", "SYSTEMS": "SYSTEMS",
            }.get(mode, "")

            current = ""
            if self.runtime:
                current = self.runtime.nav_folders.get(mode, "")

            result = self.bridge.list_category_contents(
                current, entity_type)

            folders = []
            for sf in result.get("subfolders", []):
                last = sf.split("/")[-1]
                if last.lower().startswith(search):
                    folders.append(last)
            return folders[:15]
        except Exception:
            return []
