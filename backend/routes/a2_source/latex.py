"""LaTeX project → blocks with source positions (file 03 §A2.2 steps 1–7).

1. ``assemble``: the master's text with every ``\\input``/``\\include``/``\\subfile``/``\\import`` inlined,
   resolved relative to the master's folder (or its nearest ancestor that has the path, as the
   folder-level assembler does), with a cycle guard. Commented-out includes stay out; missing ones are
   listed. Every character keeps its file and line (``Assembled.locate``), which is the source map.
2. User macros (``\\newcommand``, ``\\renewcommand``, ``\\providecommand``, ``\\def``,
   ``\\NewDocumentCommand`` with ``m``/``o``/``O{…}``/``s`` arguments) from the preamble and the folder's
   ``.sty`` files are expanded when the walker meets them, so ``\\Pc`` reads ``P_c``.
3. pylatexenc walks the document body (it keeps positions; Pandoc's LaTeX reader does not, and the
   source map needs them). The walk yields blocks: paragraphs with ``$…$`` math, display equations as
   ``$$…$$``, list items, code, tables (HTML, ``tables.py``), figures with captions and image paths.
   Formatting macros are dropped, siunitx becomes ``300 bar``, ``\\ref``/``\\Cref``/``\\eqref``/
   ``\\cite`` become the referenced number or bibliography text after the walk (labels may come later).
"""

import re
from bisect import bisect_right
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexCommentNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexMathNode,
    LatexSpecialsNode,
    LatexWalker,
    get_default_latex_context_db,
)
from pylatexenc.macrospec import EnvironmentSpec, MacroSpec, VerbatimArgsParser

from backend.routes.a2_source.bib import BibEntry, cite_text
from backend.routes.a2_source.tables import Table, TableBuilder

INCLUDE = re.compile(r"\\(input|include|subfile)\s*\{([^}]+)\}")
IMPORT = re.compile(r"\\(sub)?(?:import|inputfrom|includefrom)\s*\{([^}]*)\}\s*\{([^}]+)\}")
BEGIN_DOCUMENT = re.compile(r"\\begin\s*\{document\}")
END_DOCUMENT = re.compile(r"\\end\s*\{document\}")
BLANK_LINE = re.compile(r"\n[ \t]*\n\s*")
SPACES = re.compile(r"[ \t\r\f\v]+")
MAGIC_COMMENT = re.compile(r"^\s*%\s*!\s*TeX\b.*$", re.IGNORECASE | re.MULTILINE)
REF_MARK = re.compile("\ue000([a-zA-Z]+):([^\ue001]*)\ue001")
MAX_EXPANSION_DEPTH = 12

SECTION_LEVELS = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
    "subparagraph": 6,
}
BIG_SIZES = frozenset({"huge", "Huge", "LARGE", "Large"})
FORMAT_ONE_ARG = frozenset(
    {
        "textbf",
        "textit",
        "emph",
        "underline",
        "uline",
        "texttt",
        "textsc",
        "textsf",
        "textrm",
        "textup",
        "textmd",
        "textnormal",
        "textsl",
        "mbox",
        "makebox",
        "fbox",
        "framebox",
        "text",
        "hl",
        "mathrm",
        "boldsymbol",
        "centerline",
        "raisebox",
        "parbox",
        "resizebox",
        "scalebox",
        "colorbox",
        "textcolor",
        "hyperlink",
        "hyperref",
        "nameref",
        "phantom",
        "MakeUppercase",
        "MakeLowercase",
        "uppercase",
        "lowercase",
    }
)
SYMBOLS = {
    "%": "%",
    "&": "&",
    "_": "_",
    "#": "#",
    "$": "$",
    "{": "{",
    "}": "}",
    " ": " ",
    ",": " ",
    ";": " ",
    "quad": " ",
    "qquad": " ",
    "textdegree": "°",
    "degree": "°",
    "textmu": "µ",
    "textohm": "Ω",
    "ldots": "…",
    "dots": "…",
    "textellipsis": "…",
    "times": "×",
    "pm": "±",
    "textpm": "±",
    "textendash": "–",
    "textemdash": "—",
    "LaTeX": "LaTeX",
    "TeX": "TeX",
    "S": "§",
    "P": "¶",
    "copyright": "©",
    "textcopyright": "©",
    "textregistered": "®",
    "texttrademark": "™",
    "textless": "<",
    "textgreater": ">",
    "textbackslash": "\\",
    "textasciitilde": "~",
    "textasciicircum": "^",
    "textbar": "|",
    "textbullet": "•",
    "checkmark": "✓",
    "ss": "ß",
    "AA": "Å",
    "aa": "å",
    "o": "ø",
    "O": "Ø",
    "ae": "æ",
    "oe": "œ",
    "i": "i",
    "textquotesingle": "'",
    "textquotedbl": '"',
    "rightarrow": "→",
    "leftarrow": "←",
    "to": "→",
}
LINE_BREAKS = frozenset({"\\", "newline", "linebreak", "tabularnewline", "cr"})
REF_MACROS = {
    "ref": "ref",
    "autoref": "cref",
    "cref": "cref",
    "Cref": "cref",
    "vref": "cref",
    "Vref": "cref",
    "eqref": "eqref",
    "pageref": "ref",
    "nameref": "name",
}
CITE_MACROS = frozenset(
    {
        "cite",
        "citep",
        "citet",
        "citeauthor",
        "citeyear",
        "parencite",
        "textcite",
        "autocite",
        "footcite",
        "supercite",
        "nocite",
    }
)
SIUNITX = frozenset({"SI", "qty", "si", "unit", "num", "SIrange", "qtyrange", "numrange", "ang"})
IGNORED = frozenset(
    {
        "centering",
        "noindent",
        "indent",
        "newpage",
        "clearpage",
        "cleardoublepage",
        "pagebreak",
        "nopagebreak",
        "FloatBarrier",
        "vspace",
        "hspace",
        "vfill",
        "hfill",
        "smallskip",
        "medskip",
        "bigskip",
        "hline",
        "cline",
        "toprule",
        "midrule",
        "bottomrule",
        "cmidrule",
        "addlinespace",
        "specialrule",
        "rowcolor",
        "cellcolor",
        "rowcolors",
        "color",
        "setlength",
        "addtolength",
        "setcounter",
        "addtocounter",
        "renewcommand",
        "newcommand",
        "providecommand",
        "def",
        "tableofcontents",
        "listoffigures",
        "listoftables",
        "maketitle",
        "thispagestyle",
        "pagestyle",
        "crefalias",
        "definecolor",
        "small",
        "footnotesize",
        "scriptsize",
        "tiny",
        "large",
        "Large",
        "LARGE",
        "huge",
        "Huge",
        "normalsize",
        "bfseries",
        "itshape",
        "ttfamily",
        "rmfamily",
        "sffamily",
        "mdseries",
        "upshape",
        "raggedright",
        "raggedleft",
        "bibliographystyle",
        "addcontentsline",
        "phantomsection",
        "protect",
        "textwidth",
        "linewidth",
        "columnwidth",
        "hrule",
        "vrule",
        "strut",
        "label",
        "graphicspath",
        "fancyhead",
        "fancyfoot",
        "fancyhf",
        "geometry",
        "arraystretch",
        "tabcolsep",
        "newcolumntype",
        "linespread",
        "endhead",
        "endfirsthead",
        "endfoot",
        "endlastfoot",
        "nonumber",
        "notag",
        "unskip",
        "relax",
        "par",
        "printbibliography",
        "listfiles",
        "selectlanguage",
        "today",
        "and",
        "thanks",
        "captionsetup",
        "hypersetup",
        "titleformat",
        "titlespacing",
        "newgeometry",
        "pagenumbering",
        "newcounter",
        "usetikzlibrary",
        "setmainfont",
    }
)
FIGURE_ENVS = frozenset(
    {"figure", "figure*", "wrapfigure", "SCfigure", "sidewaysfigure", "subfigure", "subfloat"}
)
TABLE_ENVS = frozenset({"table", "table*", "sidewaystable", "wraptable", "subtable"})
TABULAR_ENVS = frozenset(
    {"tabular", "tabular*", "tabularx", "tabulary", "longtable", "supertabular", "xltabular", "tblr"}
)
MATH_ENVS = {
    "equation": None,
    "equation*": None,
    "displaymath": None,
    "math": None,
    "align": "aligned",
    "align*": "aligned",
    "flalign": "aligned",
    "flalign*": "aligned",
    "alignat": "aligned",
    "alignat*": "aligned",
    "eqnarray": "aligned",
    "eqnarray*": "aligned",
    "gather": "gathered",
    "gather*": "gathered",
    "multline": "gathered",
    "multline*": "gathered",
}
LIST_ENVS = frozenset({"itemize", "enumerate", "description", "compactitem", "compactenum", "inparaenum"})
CODE_ENVS = frozenset({"verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "alltt", "BVerbatim"})
PICTURE_ENVS = frozenset({"tikzpicture", "pgfpicture", "circuitikz", "picture", "pspicture"})
SKIPPED_ENVS = frozenset({"comment", "titlepage_skip"})


# ---------------------------------------------------------------- source files and assembly


@dataclass(frozen=True)
class SourceLoc:
    file: str
    line: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class Assembled:
    """The project as one string; ``locate(pos)`` gives the file and line a character came from."""

    text: str
    starts: list[int]
    origins: list[tuple[str, int]]  # parallel to starts: (file, offset of the piece in that file)
    line_starts: dict[str, list[int]]
    included: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    magic_comments: list[str] = field(default_factory=list)

    def locate(self, pos: int) -> SourceLoc:
        i = max(bisect_right(self.starts, pos) - 1, 0)
        file, offset = self.origins[i]
        file_pos = offset + (pos - self.starts[i])
        return SourceLoc(file, bisect_right(self.line_starts[file], file_pos))


def _line_starts(text: str) -> list[int]:
    return [0, *(m.end() for m in re.finditer("\n", text))]


def _commented(text: str, pos: int) -> bool:
    """True when an unescaped ``%`` precedes ``pos`` on its line."""
    line = text[text.rfind("\n", 0, pos) + 1 : pos]
    return re.search(r"(?<!\\)(?:\\\\)*%", line) is not None


def _normalize(path: str) -> str:
    parts: list[str] = []
    for part in PurePosixPath(path).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    return "/".join(parts).casefold()


def resolve_path(
    name: str, master_folder: str, known: Mapping[str, str], suffixes: tuple[str, ...] = (".tex",)
) -> str | None:
    """The path of ``name`` among ``known`` (normalized → path): relative to the master's folder, then to
    each ancestor of it (masters in ``Main_Files/`` include ``Sections/…`` from the project root)."""
    name = name.strip()
    candidates = [name] if PurePosixPath(name).suffix else []
    candidates += [name + s for s in suffixes]
    folders = [PurePosixPath(master_folder), *PurePosixPath(master_folder).parents]
    for folder in folders:
        for candidate in candidates:
            key = _normalize(str(folder / candidate))
            if key in known:
                return known[key]
    return None


def document_body(text: str) -> str:
    begin, end = BEGIN_DOCUMENT.search(text), END_DOCUMENT.search(text)
    if begin and end and end.start() > begin.end():
        return text[begin.end() : end.start()]
    return text


def assemble(master: str, texts: Mapping[str, str]) -> Assembled:
    """Inline the includes of ``master`` (a key of ``texts``) recursively, keeping each piece's origin."""
    known = {_normalize(path): path for path in texts}
    master_folder = str(PurePosixPath(master).parent)
    out: list[str] = []
    starts: list[int] = []
    origins: list[tuple[str, int]] = []
    missing: list[str] = []
    included: list[str] = []
    length = 0

    def emit(file: str, offset: int, piece: str) -> None:
        nonlocal length
        if piece:
            starts.append(length)
            origins.append((file, offset))
            out.append(piece)
            length += len(piece)

    def walk(path: str, start: int, end: int, stack: tuple[str, ...]) -> None:
        text = texts[path]
        matches = sorted(
            [(m.start(), m.end(), m.group(2)) for m in INCLUDE.finditer(text, start, end)]
            + [(m.start(), m.end(), f"{m.group(2)}/{m.group(3)}") for m in IMPORT.finditer(text, start, end)]
        )
        cursor = start
        for m_start, m_end, name in matches:
            if m_start < cursor or _commented(text, m_start):
                continue
            emit(path, cursor, text[cursor:m_start])
            cursor = m_end
            target = resolve_path(name, master_folder, known)
            if target is None:
                missing.append(name.strip())
                continue
            if target in stack:
                missing.append(f"{name.strip()} (include cycle)")
                continue
            included.append(target)
            body = texts[target]
            b_start, b_end = 0, len(body)
            begin, finish = BEGIN_DOCUMENT.search(body), END_DOCUMENT.search(body)
            if begin and finish and finish.start() > begin.end():  # \subfile with its own preamble
                b_start, b_end = begin.end(), finish.start()
            emit(path, m_start, "\n")
            walk(target, b_start, b_end, (*stack, target))
            emit(path, m_end, "\n")
        emit(path, cursor, text[cursor:end])

    walk(master, 0, len(texts[master]), (master,))
    magic = [m.group(0).strip() for m in MAGIC_COMMENT.finditer(texts[master])]
    return Assembled(
        text="".join(out),
        starts=starts,
        origins=origins,
        line_starts={path: _line_starts(text) for path, text in texts.items()},
        included=included,
        missing=missing,
        magic_comments=magic,
    )


# ---------------------------------------------------------------- user macros


@dataclass(frozen=True)
class UserMacro:
    name: str
    argspec: str  # pylatexenc argspec: "{" mandatory, "[" optional, "*" star
    body: str
    defaults: tuple[str | None, ...] = ()


def _group(text: str, pos: int) -> tuple[str, int] | None:
    """The balanced ``{…}`` starting at ``pos`` (after whitespace): (inner text, end position)."""
    while pos < len(text) and text[pos] in " \t\n":
        pos += 1
    if pos >= len(text) or text[pos] != "{":
        return None
    depth, i = 0, pos
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[pos + 1 : i], i + 1
        i += 1
    return None


def _bracket(text: str, pos: int) -> tuple[str, int] | None:
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    if pos >= len(text) or text[pos] != "[":
        return None
    depth, i = 0, pos
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        elif text[i] == "]" and depth == 0:
            return text[pos + 1 : i], i + 1
        i += 1
    return None


def _macro_name(text: str, pos: int) -> tuple[str, int] | None:
    """``\\name`` or ``{\\name}`` at ``pos``."""
    braced = _group(text, pos)
    if braced is not None:
        inner = braced[0].strip()
        return (inner[1:], braced[1]) if re.fullmatch(r"\\[A-Za-z@]+", inner) else None
    match = re.compile(r"\s*\\([A-Za-z@]+)").match(text, pos)
    return (match.group(1), match.end()) if match else None


XPARSE_ARG = re.compile(r"\s*(\+?)(m|o|s|O\{|t.|r..|d..|D..\{|g|G\{|e\{|E\{)")


def _xparse_spec(spec: str) -> tuple[str, tuple[str | None, ...]] | None:
    """``O{0.47\\textwidth} m m`` → (``[{{``, defaults); None for argument types we do not model."""
    argspec, defaults, pos = "", [], 0
    while pos < len(spec):
        if spec[pos].isspace():
            pos += 1
            continue
        if spec[pos] == "+":
            pos += 1
            continue
        kind = spec[pos]
        if kind == "m":
            argspec, pos = argspec + "{", pos + 1
            defaults.append(None)
        elif kind == "o":
            argspec, pos = argspec + "[", pos + 1
            defaults.append(None)
        elif kind == "s":
            argspec, pos = argspec + "*", pos + 1
            defaults.append(None)
        elif kind == "O":
            group = _group(spec, pos + 1)
            if group is None:
                return None
            argspec, pos = argspec + "[", group[1]
            defaults.append(group[0])
        else:
            return None
    return argspec, tuple(defaults)


def collect_macros(texts: list[str]) -> dict[str, UserMacro]:
    """User macro definitions of the preamble and ``.sty`` files (later definitions win)."""
    macros: dict[str, UserMacro] = {}
    pattern = re.compile(
        r"\\(newcommand|renewcommand|providecommand|NewDocumentCommand|RenewDocumentCommand|def)\*?"
    )
    for text in texts:
        for match in pattern.finditer(text):
            if _commented(text, match.start()):
                continue
            kind, pos = match.group(1), match.end()
            named = _macro_name(text, pos)
            if named is None:
                continue
            name, pos = named
            if kind == "def":
                params = re.compile(r"((?:#\d)*)").match(text, pos)
                count = len(params.group(1)) // 2 if params else 0
                body = _group(text, params.end() if params else pos)
                if body is not None:
                    macros[name] = UserMacro(name, "{" * count, body[0], (None,) * count)
                continue
            if kind in ("NewDocumentCommand", "RenewDocumentCommand"):
                spec = _group(text, pos)
                body = _group(text, spec[1]) if spec else None
                parsed = _xparse_spec(spec[0]) if spec else None
                if body is not None and parsed is not None:
                    macros[name] = UserMacro(name, parsed[0], body[0], parsed[1])
                continue
            count, default = 0, None
            bracket = _bracket(text, pos)
            if bracket is not None and bracket[0].strip().isdigit():
                count, pos = int(bracket[0]), bracket[1]
                optional = _bracket(text, pos)
                if optional is not None:
                    default, pos = optional
            body = _group(text, pos)
            if body is None:
                continue
            if default is not None:
                macros[name] = UserMacro(
                    name, "[" + "{" * (count - 1), body[0], (default,) + (None,) * (count - 1)
                )
            else:
                macros[name] = UserMacro(name, "{" * count, body[0], (None,) * count)
    return {name: macro for name, macro in macros.items() if name not in BLOCKED_REDEFINITIONS}


# Redefinitions of these change layout only; expanding them would hide the structure the walker reads.
BLOCKED_REDEFINITIONS = frozenset(
    {"section", "subsection", "subsubsection", "caption", "label", "ref", "item", "includegraphics", "cite"}
)


def preamble_title(preamble: str) -> str | None:
    match = re.search(r"\\title\s*(\[[^\]]*\])?", preamble)
    if match is None:
        return None
    group = _group(preamble, match.end())
    return group[0] if group else None


# ---------------------------------------------------------------- the walk


@dataclass
class Block:
    kind: str  # heading, para, item, equation, code, table, figure
    text: str
    pos: int
    breadcrumb: tuple[str, ...]
    level: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Label:
    kind: str  # section, table, figure, equation, item
    number: str
    title: str = ""

    def text(self, style: str) -> str:
        if style == "eqref":
            return f"({self.number})"
        if style == "cref":
            name = {"section": "Section", "table": "Table", "figure": "Figure", "equation": "Equation"}
            word = name.get(self.kind, "")
            if self.kind == "section" and self.number[:1].isalpha():
                word = "Appendix"
            if self.kind == "equation":
                return f"{word} ({self.number})"
            return f"{word} {self.number}".strip()
        if style == "name":
            return self.title or self.number
        return self.number


@dataclass
class _Float:
    kind: str
    pos: int
    caption: str | None = None
    number: str | None = None
    labels: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    tikz: bool = False
    subcaptions: list[str] = field(default_factory=list)


@dataclass
class WalkResult:
    blocks: list[Block]
    labels: dict[str, Label]
    title: str | None
    unknown_macros: dict[str, int]
    bib_files: list[str]
    inline_bib: list[BibEntry]
    failed_sections: list[str]
    unresolved_refs: list[str] = field(default_factory=list)


def _context_db(macros: Mapping[str, UserMacro]):
    db = get_default_latex_context_db()
    verbatim = VerbatimArgsParser(verbatim_arg_type="verbatim-environment")
    db.add_context_category(
        "dcl",
        prepend=True,
        macros=[
            MacroSpec("caption", "*[{"),
            MacroSpec("captionof", "*{[{"),
            MacroSpec("subcaption", "*[{"),
            MacroSpec("SI", "[{[{"),
            MacroSpec("qty", "[{{"),
            MacroSpec("si", "[{"),
            MacroSpec("unit", "[{"),
            MacroSpec("num", "[{"),
            MacroSpec("ang", "[{"),
            MacroSpec("SIrange", "[{{{"),
            MacroSpec("qtyrange", "[{{{"),
            MacroSpec("numrange", "[{{"),
            MacroSpec("multicolumn", "{{{"),
            MacroSpec("multirow", "[{[{[{"),
            MacroSpec("href", "[{{"),
            MacroSpec("hyperlink", "{{"),
            MacroSpec("hyperref", "[{"),
            MacroSpec("textcolor", "[{{"),
            MacroSpec("colorbox", "[{{"),
            MacroSpec("rowcolor", "[{"),
            MacroSpec("cellcolor", "[{"),
            MacroSpec("cmidrule", "[{"),
            MacroSpec("specialrule", "{{{"),
            MacroSpec("includepdf", "[{"),
            MacroSpec("bibliography", "{"),
            MacroSpec("addbibresource", "[{"),
            MacroSpec("bibitem", "[{"),
            MacroSpec("IfFileExists", "{{{"),
            MacroSpec("raisebox", "{[[{"),
            MacroSpec("parbox", "[[[{{"),
            MacroSpec("makebox", "[[{"),
            MacroSpec("resizebox", "*{{{"),
            MacroSpec("scalebox", "{[{"),
            MacroSpec("textsubscript", "{"),
            MacroSpec("textsuperscript", "{"),
            MacroSpec("setlength", "{{"),
            MacroSpec("addtolength", "{{"),
            MacroSpec("setcounter", "{{"),
            MacroSpec("addcontentsline", "{{{"),
            MacroSpec("crefalias", "{{"),
            MacroSpec("definecolor", "{{{"),
            MacroSpec("thispagestyle", "{"),
            MacroSpec("pagestyle", "{"),
            MacroSpec("graphicspath", "{"),
            MacroSpec("newcolumntype", "{[{"),
            MacroSpec("color", "[{"),
            MacroSpec("enquote", "*{"),
            MacroSpec("nameref", "*{"),
            MacroSpec("autoref", "*{"),
            MacroSpec("vref", "*{"),
            MacroSpec("Vref", "*{"),
            MacroSpec("cref", "*{"),
            MacroSpec("Cref", "*{"),
            MacroSpec("ensuremath", "{"),
            MacroSpec("phantom", "{"),
            MacroSpec("fancyhead", "[{"),
            MacroSpec("fancyfoot", "[{"),
            MacroSpec("geometry", "{"),
            MacroSpec("selectlanguage", "{"),
            MacroSpec("linespread", "{"),
            MacroSpec("captionsetup", "[{"),
            MacroSpec("bibliographystyle", "{"),
            MacroSpec("titleformat", "*{[{[{{["),
            MacroSpec("titlespacing", "*{{{{["),
            MacroSpec("newgeometry", "{"),
            MacroSpec("pagenumbering", "{"),
            MacroSpec("setcounter", "{{"),
            MacroSpec("newcounter", "{["),
            MacroSpec("usetikzlibrary", "{"),
            MacroSpec("setmainfont", "[{"),
            MacroSpec("hypersetup", "{"),
            MacroSpec("MakeUppercase", "{"),
            MacroSpec("MakeLowercase", "{"),
            *(MacroSpec(name, m.argspec) for name, m in macros.items()),
        ],
        environments=[
            EnvironmentSpec("tabularx", "{{"),
            EnvironmentSpec("tabulary", "{{"),
            EnvironmentSpec("xltabular", "{{"),
            EnvironmentSpec("tabular*", "{[{"),
            EnvironmentSpec("longtable", "[{"),
            EnvironmentSpec("supertabular", "{"),
            EnvironmentSpec("tblr", "[{"),
            EnvironmentSpec("minipage", "[[[{"),
            EnvironmentSpec("wrapfigure", "[{[{"),
            EnvironmentSpec("wraptable", "[{[{"),
            EnvironmentSpec("subfigure", "[{"),
            EnvironmentSpec("subtable", "[{"),
            EnvironmentSpec("multicols", "{"),
            EnvironmentSpec("adjustbox", "{"),
            EnvironmentSpec("tcolorbox", "["),
            EnvironmentSpec("thebibliography", "{"),
            EnvironmentSpec("tikzpicture", "["),
            EnvironmentSpec("circuitikz", "["),
            EnvironmentSpec("lstlisting", args_parser=verbatim),
            EnvironmentSpec("minted", args_parser=verbatim),
            EnvironmentSpec("Verbatim", args_parser=verbatim),
            EnvironmentSpec("BVerbatim", args_parser=verbatim),
            EnvironmentSpec("comment", args_parser=verbatim),
        ],
    )
    return db


def _arg(node, index: int):
    argd = getattr(node, "nodeargd", None)
    if argd is None or index >= len(argd.argnlist) or index < -len(argd.argnlist):
        return None
    return argd.argnlist[index]


def _args(node) -> list:
    argd = getattr(node, "nodeargd", None)
    return list(argd.argnlist) if argd is not None else []


def _verbatim(node) -> str:
    if node is None:
        return ""
    if isinstance(node, LatexGroupNode):
        return "".join(n.latex_verbatim() for n in node.nodelist)
    return node.latex_verbatim()


def _nodes(node) -> list:
    if node is None:
        return []
    if isinstance(node, LatexGroupNode):
        return list(node.nodelist)
    return [node]


def _alpha(n: int) -> str:
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


class Walker:
    """One pass over the document body that produces blocks, labels and a title."""

    def __init__(
        self,
        assembled_text: str,
        macros: Mapping[str, UserMacro],
        file_exists: Callable[[str], bool],
        doc_title: str,
    ):
        self.text = assembled_text
        self.macros = dict(macros)
        self.db = _context_db(self.macros)
        self.file_exists = file_exists
        self.doc_title = doc_title
        self.blocks: list[Block] = []
        self.labels: dict[str, Label] = {}
        self.unknown: dict[str, int] = {}
        self.bib_files: list[str] = []
        self.inline_bib: list[BibEntry] = []
        self.title: str | None = None
        self.counters = [0] * 7
        self.top_level = 2
        self.appendix = False
        self.headings: list[tuple[int, str]] = []
        self.label_target: tuple[str, str, str] | None = None
        self.floats: list[_Float] = []
        self.counts = {"table": 0, "figure": 0, "equation": 0}
        self.para: list[str] = []
        self.para_pos: int | None = None
        self.quantities: list[str] = []
        self.inline_depth = 0
        self.lists: list[list] = []  # [env name, counter]
        self.expansion_depth = 0
        self.seen_heading = False
        self.offset = 0

    # ------------------------------------------------------------ entry points

    def run(self, start: int, end: int) -> None:
        self.top_level = 1 if re.search(r"\\chapter\b", self.text[start:end]) else 2
        walker = LatexWalker(self.text, latex_context=self.db, tolerant_parsing=True)
        nodes, _, _ = walker.get_latex_nodes(pos=start, stop_upon_end_environment="document")
        self.walk([n for n in nodes if n.pos is None or n.pos < end])
        self.flush()

    def run_isolated(self, start: int, end: int) -> None:
        """Walk ``text[start:end]`` on its own (the per-section fallback after a failed full walk)."""
        walker = LatexWalker(self.text[start:end], latex_context=self.db, tolerant_parsing=True)
        nodes, _, _ = walker.get_latex_nodes()
        self.offset = start
        try:
            self.walk(nodes)
            self.flush()
        finally:
            self.offset = 0

    def walk(self, nodes, pos: int | None = None) -> None:
        for node in nodes:
            if node is None:
                continue
            p = pos if pos is not None else (node.pos or 0) + self.offset
            if isinstance(node, LatexCharsNode):
                self.chars(node.chars, p, exact=pos is None)
            elif isinstance(node, LatexCommentNode):
                continue
            elif isinstance(node, LatexMathNode):
                self.math(node, p)
            elif isinstance(node, LatexGroupNode):
                if not self._title_candidate(node.nodelist, p):
                    self.walk(node.nodelist, pos)
            elif isinstance(node, LatexSpecialsNode):
                self.specials(node, p)
            elif isinstance(node, LatexMacroNode):
                self.macro(node, p, pos)
            elif isinstance(node, LatexEnvironmentNode):
                self.environment(node, p, pos)

    # ------------------------------------------------------------ text accumulation

    def add(self, text: str, pos: int) -> None:
        if not text:
            return
        if self.para_pos is None and text.strip():
            self.para_pos = pos
        self.para.append(text)

    def chars(self, chars: str, pos: int, exact: bool = False) -> None:
        """Text; a blank line ends the paragraph. With ``exact`` (not inside a macro expansion) each
        piece's position is its first visible character, so the source line is the text's own line."""
        if self.inline_depth:
            self.add(SPACES.sub(" ", chars.replace("\n", " ")), pos)
            return
        cursor = 0
        for i, piece in enumerate(BLANK_LINE.split(chars)):
            start = chars.find(piece, cursor) if piece else cursor
            cursor = start + len(piece)
            if i:
                self.flush()
            lead = len(piece) - len(piece.lstrip())
            self.add(SPACES.sub(" ", piece.replace("\n", " ")), pos + start + lead if exact else pos)

    def specials(self, node, pos: int) -> None:
        chars = node.specials_chars
        mapping = {
            "~": " ",
            "--": "–",
            "---": "—",
            "``": "“",
            "''": "”",
            "`": "‘",
            "'": "’",
            "!`": "¡",
            "?`": "¿",
        }
        if chars == "&":
            self.add(" ", pos)
        else:
            self.add(mapping.get(chars, chars), pos)

    def flush(self, kind: str = "para", **meta: Any) -> None:
        if self.inline_depth:
            return
        text = "".join(self.para)
        text = "\n".join(SPACES.sub(" ", line).strip() for line in text.split("\n"))
        text = re.sub(r"\n{2,}", "\n", text).strip()
        if text:
            if self.lists and kind == "para":
                kind = "item"
            if kind == "item" and self.lists:
                meta.setdefault("list", self.lists[-1][0])
            if self.quantities:
                meta["quantities"] = list(self.quantities)
            self.blocks.append(
                Block(kind, text, self.para_pos or 0, self.breadcrumb(), len(self.headings) + 1, meta)
            )
        self.para, self.para_pos, self.quantities = [], None, []

    def inline(self, nodes, pos: int | None) -> str:
        """Render nodes to one line of text (captions, cells, titles) without emitting blocks."""
        saved = (self.para, self.para_pos, self.quantities)
        self.para, self.para_pos, self.quantities = [], None, []
        self.inline_depth += 1
        try:
            self.walk(nodes, pos)
            text = "".join(self.para)
        finally:
            self.inline_depth -= 1
            quantities = self.quantities
            self.para, self.para_pos, self.quantities = saved
            self.quantities += quantities
        return SPACES.sub(" ", text.replace("\n", " ")).strip()

    def breadcrumb(self) -> tuple[str, ...]:
        return (self.doc_title, *(title for _, title in self.headings))

    # ------------------------------------------------------------ math

    def expand_text(self, body: str) -> str:
        """User macros inside math (kept verbatim, so not walked): ``$\\Pc$`` → ``$P_c$``."""
        if not self.macros:
            return body
        pattern = re.compile(r"\\([A-Za-z@]+)")
        for _ in range(MAX_EXPANSION_DEPTH):
            out, cursor, changed = [], 0, False
            for match in pattern.finditer(body):
                macro = self.macros.get(match.group(1))
                if macro is None or match.start() < cursor:
                    continue
                pos, values = match.end(), []
                for i, kind in enumerate(macro.argspec):
                    if kind == "*":
                        star = body.startswith("*", pos)
                        values.append("*" if star else "")
                        pos += int(star)
                        continue
                    found = _bracket(body, pos) if kind == "[" else _group(body, pos)
                    if found is None:
                        values.append((macro.defaults[i] if i < len(macro.defaults) else None) or "")
                        if kind == "{":  # a bare token argument: \\frac12 style
                            token = re.compile(r"\s*(\\[A-Za-z]+|\S)").match(body, pos)
                            if token:
                                values[-1], pos = token.group(1), token.end()
                        continue
                    values.append(found[0])
                    pos = found[1]
                replacement = macro.body
                for i in range(len(values), 0, -1):
                    replacement = replacement.replace(f"#{i}", values[i - 1])
                out += [body[cursor : match.start()], replacement]
                cursor, changed = pos, True
            if not changed:
                return body
            body = "".join(out) + body[cursor:]
        return body

    def math(self, node, pos: int) -> None:
        body = self.expand_text("".join(n.latex_verbatim() for n in node.nodelist).strip())
        if node.displaytype == "inline":
            self.add(f"${body}$", pos)
            return
        self.equation(body, pos, numbered=False)

    def equation(self, body: str, pos: int, numbered: bool, wrapper: str | None = None) -> None:
        body = self.expand_text(body)
        labels = re.findall(r"\\label\s*\{([^}]*)\}", body)
        body = re.sub(r"\\(label\s*\{[^}]*\}|nonumber|notag)", "", body).strip()
        number = None
        if numbered:
            self.counts["equation"] += 1
            number = str(self.counts["equation"])
            for key in labels:
                self.labels[key] = Label("equation", number)
        if wrapper:
            body = f"\\begin{{{wrapper}}}{body}\\end{{{wrapper}}}"
        text = f"$${body}$$" + (f" ({number})" if number else "")
        if self.inline_depth:
            self.add(text, pos)
            return
        self.flush()
        self.para_pos = pos
        self.para = [text]
        self.flush("equation", number=number, labels=labels)

    def math_environment(self, node, pos: int) -> None:
        name = node.environmentname
        body = self.expand_text("".join(n.latex_verbatim() for n in node.nodelist))
        wrapper = MATH_ENVS[name]
        starred = name.endswith("*") or name in ("displaymath", "math")
        if wrapper == "aligned" and not starred:
            rows = re.split(r"\\\\", body)
            numbered_rows = [r for r in rows if r.strip() and not re.search(r"\\(nonumber|notag)", r)]
            first = self.counts["equation"] + 1
            for row in numbered_rows:
                self.counts["equation"] += 1
                for key in re.findall(r"\\label\s*\{([^}]*)\}", row):
                    self.labels[key] = Label("equation", str(self.counts["equation"]))
            last = self.counts["equation"]
            clean = re.sub(r"\\(label\s*\{[^}]*\}|nonumber|notag)", "", body).strip()
            text = f"$$\\begin{{aligned}}{clean}\\end{{aligned}}$$"
            if numbered_rows:
                text += f" ({first})" if first == last else f" ({first}–{last})"
            self.flush()
            self.para_pos, self.para = pos, [text]
            self.flush("equation", number=str(first) if numbered_rows else None)
            return
        self.equation(body, pos, numbered=not starred, wrapper=wrapper)

    # ------------------------------------------------------------ macros

    def macro(self, node, pos: int, override: int | None) -> None:
        name = node.macroname
        if name in self.macros and self.expansion_depth < MAX_EXPANSION_DEPTH:
            self.expand(node, pos)
            return
        if name in SECTION_LEVELS:
            self.heading(node, pos)
        elif name in LINE_BREAKS:
            self.add("\n", pos)
        elif name in SYMBOLS:
            self.add(SYMBOLS[name], pos)
        elif name == "label":
            self.label(_verbatim(_arg(node, 0)).strip())
        elif name in ("caption", "captionof", "subcaption"):
            self.caption(node, pos)
        elif name == "includegraphics":
            self.graphic(_path(_verbatim(_arg(node, -1))), pos)
        elif name == "includepdf":
            self.include_pdf(node, pos)
        elif name in REF_MACROS:
            keys = _verbatim(_arg(node, -1))
            refs = [f"\ue000{REF_MACROS[name]}:{k.strip()}\ue001" for k in keys.split(",") if k.strip()]
            self.add(", ".join(refs), pos)
        elif name in CITE_MACROS:
            keys = [k.strip() for k in _verbatim(_arg(node, -1)).split(",") if k.strip()]
            if name != "nocite" and keys:
                self.add("\ue000cite:" + ",".join(keys) + "\ue001", pos)
        elif name in SIUNITX:
            self.siunitx(node, pos)
        elif name in ("textsubscript", "textsuperscript"):
            mark = "_" if name == "textsubscript" else "^"
            self.add(mark + self.inline(_nodes(_arg(node, 0)), override), pos)
        elif name == "href":
            url = _verbatim(_arg(node, 1)).strip()
            text = self.inline(_nodes(_arg(node, 2)), override)
            self.add(f"{text} ({url})" if text and text != url else url, pos)
        elif name == "url":
            self.add(_verbatim(_arg(node, 0)).strip(), pos)
        elif name == "verb":
            self.add("`" + _verbatim(_arg(node, -1)) + "`", pos)
        elif name == "footnote":
            self.add(f" (footnote: {self.inline(_nodes(_arg(node, -1)), override)})", pos)
        elif name == "enquote":
            self.add(f"“{self.inline(_nodes(_arg(node, -1)), override)}”", pos)
        elif name == "ensuremath":
            self.add(f"${_verbatim(_arg(node, 0))}$", pos)
        elif name == "item":
            self.flush()
            label = _arg(node, 0)
            if self.lists:
                self.lists[-1][1] += 1
            if label is not None:
                self.add(self.inline(_nodes(label), override) + " ", pos)
            elif self.lists and self.lists[-1][0] in ("enumerate", "compactenum", "inparaenum"):
                self.add(f"{self.lists[-1][1]}. ", pos)
            else:
                self.add("- ", pos)
        elif name == "IfFileExists":
            branch = 1 if self.file_exists(_verbatim(_arg(node, 0)).strip()) else 2
            self.walk(_nodes(_arg(node, branch)), override)
        elif name in ("bibliography", "addbibresource"):
            self.bib_files += [p.strip() for p in _verbatim(_arg(node, -1)).split(",") if p.strip()]
        elif name == "appendix":
            self.enter_appendix()
        elif name in ("title",):
            self.title = self.inline(_nodes(_arg(node, -1)), override) or self.title
        elif name in ("author", "date"):
            return
        elif name in ("textcolor", "colorbox"):
            self.walk(_nodes(_arg(node, 2)), override)
        elif name in ("multicolumn",):
            self.walk(_nodes(_arg(node, 2)), override)
        elif name in ("multirow",):
            self.walk(_nodes(_arg(node, 5)), override)
        elif name in FORMAT_ONE_ARG:
            args = [a for a in _args(node) if a is not None]
            if args and not self._title_candidate(_nodes(args[-1]), pos):
                self.walk(_nodes(args[-1]), override)
        elif name in IGNORED:
            return
        else:
            self.unknown[name] = self.unknown.get(name, 0) + 1
            for arg in _args(node):
                if isinstance(arg, LatexGroupNode):
                    self.walk(arg.nodelist, override)

    def walk_text(self, text: str, pos: int) -> None:
        walker = LatexWalker(text, latex_context=self.db, tolerant_parsing=True)
        nodes, _, _ = walker.get_latex_nodes()
        self.expansion_depth += 1
        try:
            self.walk(nodes, pos)
        finally:
            self.expansion_depth -= 1

    def include_pdf(self, node, pos: int) -> None:
        """``\\includepdf[pagecommand={\\section{…}\\label{…}}]{file}``: the page command carries the
        appendix headings; the PDF itself is recorded once as an included document."""
        options = _verbatim(_arg(node, 0))
        command = re.search(r"pagecommand\s*=\s*", options)
        if command is not None:
            group = _group(options, command.end())
            if group is not None:
                self.walk_text(group[0], pos)
        path = _path(_verbatim(_arg(node, -1)))
        self.flush()
        previous = self.blocks[-1] if self.blocks else None
        if previous is not None and previous.kind == "figure" and previous.meta.get("images") == [path]:
            return
        self.blocks.append(
            Block(
                "figure",
                "",
                pos,
                self.breadcrumb(),
                len(self.headings) + 1,
                {"images": [path], "included_pdf": True, "caption": None},
            )
        )

    def tabbing(self, node, pos: int) -> None:
        """``tabbing``: ``\\kill`` lines set tab stops only; ``\\=`` and ``\\>`` become spaces."""
        body = "".join(n.latex_verbatim() for n in node.nodelist)
        pieces = re.split(r"(\\\\|\\kill\b)", body)
        lines = [
            pieces[i] for i in range(0, len(pieces), 2) if i + 1 >= len(pieces) or pieces[i + 1] != r"\kill"
        ]
        lines = [re.sub(r"\\[=><+\-]", "  ", line) for line in lines]
        self.walk_text(r" \\ ".join(lines), pos)
        self.flush()

    def expand(self, node, pos: int) -> None:
        macro = self.macros[node.macroname]
        args = _args(node)
        body = macro.body
        for i in range(len(macro.argspec), 0, -1):
            arg = args[i - 1] if i - 1 < len(args) else None
            if macro.argspec[i - 1] == "*":
                value = "*" if arg is not None else ""
            elif arg is None:
                value = macro.defaults[i - 1] if i - 1 < len(macro.defaults) else ""
                value = value or ""
            else:
                value = _verbatim(arg)
            body = body.replace(f"#{i}", value)
        walker = LatexWalker(body, latex_context=self.db, tolerant_parsing=True)
        nodes, _, _ = walker.get_latex_nodes()
        self.expansion_depth += 1
        try:
            self.walk(nodes, pos)
        finally:
            self.expansion_depth -= 1

    def _title_candidate(self, nodes, pos: int) -> bool:
        """``{\\huge Title}`` or ``\\textbf{\\Huge Title}`` before the first heading is the document title."""
        if self.title is not None or self.seen_heading or self.inline_depth:
            return False
        first = next((n for n in nodes if not (isinstance(n, LatexCharsNode) and not n.chars.strip())), None)
        if not (isinstance(first, LatexMacroNode) and first.macroname in BIG_SIZES):
            return False
        text = self.inline(nodes, pos)
        if not text:
            return False
        self.title = text
        self.flush()
        return True

    def heading(self, node, pos: int) -> None:
        self.flush()
        self.seen_heading = True
        level = SECTION_LEVELS[node.macroname]
        starred = _arg(node, 0) is not None
        title = self.inline(_nodes(_arg(node, 2)), pos)
        number = ""
        if not starred:
            self.counters[level] += 1
            for deeper in range(level + 1, len(self.counters)):
                self.counters[deeper] = 0
            parts = [self.counters[lv] for lv in range(self.top_level, level + 1)]
            if parts and all(parts):
                head = _alpha(parts[0]) if self.appendix else str(parts[0])
                number = ".".join([head, *map(str, parts[1:])])
        shown = f"{number} {title}".strip() if number else title
        self.headings = [(lv, t) for lv, t in self.headings if lv < level] + [(level, shown)]
        self.label_target = ("section", number or title, title)
        self.blocks.append(
            Block(
                "heading",
                shown,
                pos,
                self.breadcrumb(),
                len(self.headings),
                {"number": number, "title": title},
            )
        )

    def enter_appendix(self) -> None:
        if not self.appendix:
            self.appendix = True
            self.counters[self.top_level] = 0

    def label(self, key: str) -> None:
        if not key:
            return
        if self.floats and self.floats[-1].number is not None:
            current = self.floats[-1]
            self.labels[key] = Label(current.kind, current.number, current.caption or "")
            current.labels.append(key)
        elif self.label_target is not None:
            kind, number, title = self.label_target
            self.labels[key] = Label(kind, number, title)
        elif self.lists:
            self.labels[key] = Label("item", str(self.lists[-1][1]))

    def caption(self, node, pos: int) -> None:
        starred = _arg(node, 0) is not None
        text = self.inline(_nodes(_arg(node, -1)), pos)
        if not self.floats:
            self.flush()
            self.add(text, pos)
            self.flush()
            return
        current = self.floats[-1]
        kind = current.kind if node.macroname != "captionof" else _verbatim(_arg(node, 1)).strip()
        if current.caption is not None and node.macroname != "subcaption":
            current.subcaptions.append(text)
            return
        current.caption = text
        if not starred and kind in self.counts:
            self.counts[kind] += 1
            current.number = str(self.counts[kind])
            current.kind = kind

    def graphic(self, path: str, pos: int) -> None:
        if self.floats:
            self.floats[-1].images.append(path)
            return
        self.flush()
        self.blocks.append(
            Block("figure", "", pos, self.breadcrumb(), len(self.headings) + 1, {"images": [path]})
        )

    def siunitx(self, node, pos: int) -> None:
        name = node.macroname
        groups = [_verbatim(a) for a in _args(node) if isinstance(a, LatexGroupNode)]
        if not groups:
            return
        if name in ("SI", "qty"):
            text = f"{_number(groups[0])} {unit_text(groups[-1])}".strip() if len(groups) > 1 else groups[0]
        elif name in ("si", "unit"):
            text = unit_text(groups[-1])
        elif name == "num":
            text = _number(groups[-1])
        elif name == "ang":
            text = _number(groups[-1]) + "°"
        elif len(groups) >= 2:
            unit = unit_text(groups[2]) if len(groups) > 2 else ""
            text = f"{_number(groups[0])}–{_number(groups[1])} {unit}".strip()
        else:
            text = groups[0]
        if text:
            if name in ("SI", "qty", "SIrange", "qtyrange", "ang"):
                self.quantities.append(text)
            self.add(text, pos)

    # ------------------------------------------------------------ environments

    def environment(self, node, pos: int, override: int | None) -> None:
        name = node.environmentname
        if name in SKIPPED_ENVS:
            return
        if name in MATH_ENVS:
            self.math_environment(node, pos)
        elif name in FIGURE_ENVS or name in TABLE_ENVS:
            self.float_environment(node, pos, override)
        elif name in TABULAR_ENVS:
            self.tabular(node, pos, override)
        elif name in LIST_ENVS:
            self.flush()
            self.lists.append([name, 0])
            self.walk(node.nodelist, override)
            self.flush()
            self.lists.pop()
        elif name in CODE_ENVS:
            self.code(node, pos)
        elif name in PICTURE_ENVS:
            if self.floats:
                self.floats[-1].tikz = True
            else:
                self.flush()
                self.blocks.append(
                    Block(
                        "figure",
                        "",
                        pos,
                        self.breadcrumb(),
                        len(self.headings) + 1,
                        {"images": [], "tikz": True},
                    )
                )
        elif name == "tabbing":
            self.flush()
            self.tabbing(node, pos)
        elif name == "thebibliography":
            self.bibliography_environment(node)
        elif name == "appendices":
            self.flush()
            self.enter_appendix()
            self.walk(node.nodelist, override)
        elif name == "abstract":
            self.flush()
            self.headings = [(self.top_level, "Abstract")]
            self.walk(node.nodelist, override)
            self.flush()
        else:
            self.walk(node.nodelist, override)

    def code(self, node, pos: int) -> None:
        raw = node.latex_verbatim()
        body = re.sub(r"^\\begin\s*\{[^}]*\}(\s*\[[^\]]*\])?(\s*\{[^}]*\})?", "", raw)
        body = re.sub(r"\\end\s*\{[^}]*\}\s*$", "", body).strip("\n")
        if self.inline_depth:
            self.add(body, pos)
            return
        self.flush()
        self.blocks.append(
            Block("code", f"```\n{body}\n```", pos, self.breadcrumb(), len(self.headings) + 1, {})
        )

    def float_environment(self, node, pos: int, override: int | None) -> None:
        kind = "figure" if node.environmentname in FIGURE_ENVS else "table"
        if self.floats and node.environmentname in ("subfigure", "subtable", "subfloat"):
            parent = self.floats[-1]
            sub = _Float(kind, pos)
            self.floats.append(sub)
            self.walk(node.nodelist, override)
            self.floats.pop()
            parent.images += sub.images
            parent.tables += sub.tables
            if sub.caption:
                parent.subcaptions.append(sub.caption)
            for key in sub.labels:
                self.labels[key] = Label(parent.kind, parent.number or "", parent.caption or "")
            return
        self.flush()
        current = _Float(kind, pos)
        self.floats.append(current)
        saved_para, saved_pos = self.para, self.para_pos
        self.para, self.para_pos = [], None
        self.inline_depth += 1
        try:
            self.walk(node.nodelist, override)
        finally:
            self.inline_depth -= 1
            loose = "\n".join(
                line for line in (SPACES.sub(" ", x).strip() for x in "".join(self.para).split("\n")) if line
            )
            self.para, self.para_pos = saved_para, saved_pos
            self.floats.pop()
        self.emit_float(current, loose)

    def emit_float(self, current: _Float, loose: str) -> None:
        crumb, level = self.breadcrumb(), len(self.headings) + 1
        meta = {"caption": current.caption, "number": current.number, "labels": current.labels}
        if current.subcaptions:
            meta["subcaptions"] = current.subcaptions
        for i, table in enumerate(current.tables):
            caption = current.caption if i == 0 else None
            self.blocks.append(
                Block(
                    "table",
                    table.html(caption),
                    current.pos,
                    crumb,
                    level,
                    {**meta, "caption": caption, "grid": table.grid(), "header_rows": table.header_rows},
                )
            )
        if current.images or current.tikz or (current.kind == "figure" and not current.tables):
            self.blocks.append(
                Block(
                    "figure",
                    "",
                    current.pos,
                    crumb,
                    level,
                    {**meta, "images": current.images, "tikz": current.tikz, "loose_text": loose or None},
                )
            )
        elif current.kind == "table" and not current.tables and (current.caption or loose):
            self.blocks.append(
                Block("para", " ".join(filter(None, [current.caption, loose])), current.pos, crumb, level, {})
            )

    def tabular(self, node, pos: int, override: int | None) -> None:
        builder = TableBuilder()
        cell: list = []

        def end_cell() -> None:
            builder.add_cell(cell, lambda nodes: self.inline(nodes, override))
            cell.clear()

        for child in node.nodelist:
            if isinstance(child, LatexSpecialsNode) and child.specials_chars == "&":
                end_cell()
            elif isinstance(child, LatexMacroNode) and child.macroname in ("\\", "tabularnewline", "cr"):
                end_cell()
                builder.end_row()
            elif isinstance(child, LatexMacroNode) and child.macroname in (
                "hline",
                "toprule",
                "midrule",
                "cline",
                "cmidrule",
                "bottomrule",
            ):
                builder.rule(child.macroname)
            elif isinstance(child, LatexMacroNode) and child.macroname in (
                "endhead",
                "endfirsthead",
                "endfoot",
                "endlastfoot",
            ):
                end_cell()
                builder.marker(child.macroname)
            elif isinstance(child, LatexMacroNode) and child.macroname == "rowcolor":
                builder.row_colored()
            elif isinstance(child, LatexMacroNode) and child.macroname == "caption":
                if not self.floats:
                    self.floats.append(_Float("table", pos))
                    self.caption(child, pos)
                    lone = self.floats.pop()
                    builder.caption, builder.number = lone.caption, lone.number
                    builder.labels += lone.labels
                else:
                    self.caption(child, pos)
            elif isinstance(child, LatexMacroNode) and child.macroname == "label" and not self.floats:
                builder.labels.append(_verbatim(_arg(child, 0)).strip())
            else:
                cell.append(child)
        end_cell()
        builder.end_row()
        table = builder.build()
        if table is None:
            return
        if self.floats:
            self.floats[-1].tables.append(table)
            return
        number = builder.number
        for key in builder.labels:
            self.labels[key] = Label("table", number or "", builder.caption or "")
        self.flush()
        self.blocks.append(
            Block(
                "table",
                table.html(builder.caption),
                pos,
                self.breadcrumb(),
                len(self.headings) + 1,
                {
                    "caption": builder.caption,
                    "number": number,
                    "labels": builder.labels,
                    "grid": table.grid(),
                    "header_rows": table.header_rows,
                },
            )
        )

    def bibliography_environment(self, node) -> None:
        self.flush()
        key, current, items = None, [], []
        for child in node.nodelist:
            if isinstance(child, LatexMacroNode) and child.macroname == "bibitem":
                if key is not None:
                    items.append((key, current))
                key, current = _verbatim(_arg(child, -1)).strip(), []
            elif key is not None:
                current.append(child)
        if key is not None:
            items.append((key, current))
        for key, nodes in items:
            self.inline_bib.append(
                BibEntry(key=key, entry_type="bibitem", fields={"text": self.inline(nodes, None)})
            )


# ---------------------------------------------------------------- siunitx

UNIT_MACROS = {
    "bar": "bar",
    "pascal": "Pa",
    "psi": "psi",
    "meter": "m",
    "metre": "m",
    "gram": "g",
    "kilogram": "kg",
    "second": "s",
    "minute": "min",
    "hour": "h",
    "newton": "N",
    "watt": "W",
    "joule": "J",
    "volt": "V",
    "ampere": "A",
    "ohm": "Ω",
    "hertz": "Hz",
    "kelvin": "K",
    "degreeCelsius": "°C",
    "celsius": "°C",
    "degree": "°",
    "percent": "%",
    "liter": "L",
    "litre": "L",
    "mole": "mol",
    "candela": "cd",
    "byte": "B",
    "bit": "bit",
    "radian": "rad",
}
UNIT_PREFIXES = {
    "kilo": "k",
    "mega": "M",
    "giga": "G",
    "milli": "m",
    "micro": "µ",
    "nano": "n",
    "centi": "c",
    "deci": "d",
    "hecto": "h",
}


def unit_text(unit: str) -> str:
    """siunitx unit macros → a pint-readable unit (``\\kilo\\pascal\\per\\second`` → ``kPa/s``)."""
    unit = unit.strip()
    if "\\" not in unit:
        return unit.replace("~", " ").strip()
    out, prefix, per = "", "", False
    for piece, power in re.findall(r"\\([A-Za-z]+)(?:\{(\d)\})?", unit):
        if piece in UNIT_PREFIXES:
            prefix += UNIT_PREFIXES[piece]
            continue
        if piece == "per":
            per = True
            continue
        if piece in ("square", "squared"):
            out += "^2"
            continue
        if piece in ("cubic", "cubed"):
            out += "^3"
            continue
        if piece in ("tothe", "raiseto"):
            out += f"^{power}" if power else ""
            continue
        symbol = prefix + UNIT_MACROS.get(piece, piece)
        prefix = ""
        if out:
            out += "/" if per else "·"
        out += symbol
        per = False
    remainder = re.sub(r"\\[A-Za-z]+(\{\d\})?", "", unit).strip(" .~")
    return (out + (" " + remainder if remainder else "")).strip()


def _path(value: str) -> str:
    """A file argument as written (``Test\\_plots/a\\_b.png`` → ``Test_plots/a_b.png``)."""
    return re.sub(r"\\([_&%#$ ])", r"\1", value).strip().strip('"')


def _number(value: str) -> str:
    value = value.strip().replace("\\pm", "±").replace("+-", "±")
    value = re.sub(r"\s*e\s*([+-]?\d+)", r"e\1", value)
    return value.replace("~", " ")


# ---------------------------------------------------------------- references after the walk


def resolve_refs(blocks: list[Block], labels: Mapping[str, Label], bib: Mapping[str, BibEntry]) -> list[str]:
    """Replace the reference marks the walker left with numbers and bibliography text; returns the keys
    nothing defines. Each referenced label records which blocks cite it (``metadata.referenced_by``)."""
    unresolved: list[str] = []

    def replace(match: re.Match[str], block: Block) -> str:
        style, keys = match.group(1), match.group(2)
        if style == "cite":
            parts = []
            for key in keys.split(","):
                entry = bib.get(key)
                if entry is None:
                    unresolved.append(f"cite:{key}")
                    parts.append(key)
                else:
                    parts.append(cite_text(entry))
            return "[" + "; ".join(parts) + "]"
        label = labels.get(keys)
        if label is None:
            unresolved.append(f"{style}:{keys}")
            return f"[{keys}]"
        block.meta.setdefault("refs", []).append(keys)
        return label.text(style)

    for block in blocks:
        if "\ue000" in block.text:
            block.text = REF_MARK.sub(lambda m, b=block: replace(m, b), block.text)
        for key in ("caption", "loose_text"):
            value = block.meta.get(key)
            if isinstance(value, str) and "\ue000" in value:
                block.meta[key] = REF_MARK.sub(lambda m, b=block: replace(m, b), value)
        if "grid" in block.meta:
            block.meta["grid"] = [
                [REF_MARK.sub(lambda m, b=block: replace(m, b), c) for c in row] for row in block.meta["grid"]
            ]
    return sorted(set(unresolved))
