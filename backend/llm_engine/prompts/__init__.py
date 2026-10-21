"""Versioned prompt files (file 10 §2.1 rule 4). Never inline prompt strings in code.

A prompt lives in `<area>/<name>.v<N>.md`: the system text, then a line `--- user ---`, then the user
template with `$variables` (string.Template, so JSON braces in prompts need no escaping). The version is
the file stem (`triage_page.v1`); it goes into llm_calls, the vision cache key and the CIR. Changing a prompt
means adding a new file and bumping the pin in the caller, so old cache entries and ledger rows stay
attributable.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent
USER_MARKER = "\n--- user ---\n"


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    user_template: Template

    def render_user(self, **variables: str) -> str:
        return self.user_template.substitute(variables)


@cache
def load_prompt(area: str, version: str) -> Prompt:
    """Load `prompts/<area>/<version>.md`, e.g. load_prompt("vision", "triage_page.v1")."""
    path = PROMPTS_DIR / area / f"{version}.md"
    text = path.read_text(encoding="utf-8")
    if USER_MARKER not in text:
        raise ValueError(f"{path} has no '--- user ---' line")
    system, user = text.split(USER_MARKER, 1)
    return Prompt(version=version, system=system.strip(), user_template=Template(user.strip()))
