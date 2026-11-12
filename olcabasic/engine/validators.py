"""
Input checks used by the engine before anything is written to openLCA.

Each function returns an error message, or None when the value is fine.
"""

import re
import uuid
from typing import Optional

def validate_category(category: str) -> Optional[str]:
    """Return an error message if the category contains path traversal, else None."""
    if not category:
        return None
    if '/..' in category or '../' in category or category == '..':
        return (
            f"Category '{category}' contains path traversal sequences (..). "
            f"Use a plain category path like 'Processes/Energy'."
        )
    return None


def validate_param_name(name: str, index: int = 0) -> Optional[str]:
    """Return an error message if a parameter name is invalid, else None."""
    if not name or not name.strip():
        return f"Parameter {index}: name cannot be empty."
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', name):
        return (
            f"Parameter {index}: name '{name}' is invalid. "
            f"Parameter names must start with a letter or underscore "
            f"and contain only letters, digits, and underscores."
        )
    return None


FORMULA_ALLOWED = re.compile(
    r'^[A-Za-z0-9_\s\.\+\-\*/\(\),\^%<>=!&|?:]+$'
)

def validate_formula(formula: str, index: int = 0) -> Optional[str]:
    """Return an error message if a formula contains suspicious content, else None."""
    if not formula:
        return None
    # Reject anything with import, exec, eval, open, os., sys., subprocess
    dangerous = re.search(
        r'(__import__|import\s*\(|exec|eval|open\s*\(|os\.|sys\.|subprocess)',
        formula,
    )
    if dangerous:
        return (
            f"Exchange {index}: formula contains disallowed pattern "
            f"'{dangerous.group()}'. Formulas should contain only "
            f"arithmetic expressions and parameter names."
        )
    # Reject characters outside the allowed set for openLCA formulas
    if not FORMULA_ALLOWED.match(formula):
        bad_chars = set(c for c in formula if not re.match(r'[A-Za-z0-9_\s\.\+\-\*/\(\),\^%<>=!&|?:]', c))
        return (
            f"Exchange {index}: formula contains invalid characters: "
            f"{bad_chars}. openLCA formulas support arithmetic "
            f"expressions, parameter names, and functions like "
            f"min(), max(), abs(), sqrt(), ln(), exp()."
        )
    return None


def validate_uuid(value: str, field_name: str = "ID") -> Optional[str]:
    """Return an error message if the value is not a valid UUID, else None."""
    if not value:
        return None
    try:
        uuid.UUID(value)
        return None
    except (ValueError, AttributeError):
        return f"{field_name} '{value}' is not a valid UUID."
