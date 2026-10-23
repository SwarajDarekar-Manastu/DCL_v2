"""Source code → symbols with Tree-sitter (file 03 §6 steps 2–6, 8): Python, C, MATLAB.

One walker per language reads the top level of the syntax tree:
- the module header: module docstring (or the leading comment block), imports, module-level constants
  (literal assignments, ``#define``), dataclasses;
- symbols: functions, classes and their methods (MATLAB ``classdef`` methods, C ``struct``/``enum`` types),
  each with its source range, signature, docstring (Python string, MATLAB help comment, C comment above),
  parameters (with a unit from the name suffix or the docstring), and the names it calls;
- script code (statements outside any definition) in groups of at most ``BODY_LINES`` lines.

Units in names: ``P_ATM_BAR``, ``max_chamber_psi``, ``pressure_kpa`` (the last ``_`` part), or a docstring
line ``pressure (bar)`` / ``pressure [bar]`` / ``:param pressure: … in bar``.
"""

import re
from dataclasses import dataclass, field
from functools import cache
from typing import Any

BODY_LINES = 60
MAX_SYMBOL_CHARS = 6000  # ~1,500 tokens (file 03 §6 step 4)
UNIT_SUFFIXES = {
    "bar": "bar",
    "barg": "bar(g)",
    "bara": "bar(a)",
    "psi": "psi",
    "psig": "psig",
    "psia": "psia",
    "pa": "Pa",
    "kpa": "kPa",
    "mpa": "MPa",
    "k": "K",
    "degc": "°C",
    "celsius": "°C",
    "s": "s",
    "sec": "s",
    "ms": "ms",
    "us": "µs",
    "hz": "Hz",
    "khz": "kHz",
    "n": "N",
    "kn": "kN",
    "w": "W",
    "kw": "kW",
    "v": "V",
    "mv": "mV",
    "a": "A",
    "ma": "mA",
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "g": "g",
    "kg": "kg",
    "gs": "g/s",
    "kgs": "kg/s",
    "pct": "%",
    "percent": "%",
    "deg": "°",
    "rad": "rad",
    "l": "L",
    "ml": "mL",
    "lpm": "L/min",
    "sccm": "sccm",
    "ohm": "Ω",
    "nm": "N·m",
}
DOC_UNIT = re.compile(
    r"^\s*[:@]?(?:param\s+)?(\w+)\s*(?::[^\n]*?)?[(\[]\s*([A-Za-z°µ%/·^0-9()]{1,12})\s*[)\]]", re.M
)
DOC_UNIT_IN = re.compile(r"^\s*:param\s+(\w+):[^\n]*?\bin\s+([A-Za-z°µ%/]{1,8})\b", re.M)
ANNOTATION = re.compile(r"\b(TODO|FIXME|XXX|HACK|BUG)\b[:\s-]*(.*)")
LITERALS = {
    "python": {"integer", "float", "string", "true", "false", "none", "concatenated_string"},
    "c": {"number_literal", "string_literal", "char_literal", "true", "false"},
    "matlab": {"number", "string", "boolean"},
}


@dataclass
class Param:
    name: str
    annotation: str | None = None
    default: str | None = None
    unit: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class Constant:
    name: str
    value: str
    line: int
    unit: str | None = None


@dataclass
class Symbol:
    qualname: str
    name: str
    kind: str  # function, method, class, type, body
    start_line: int
    end_line: int
    text: str
    signature: str = ""
    docstring: str | None = None
    params: list[Param] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    parent: str | None = None
    preamble: str = ""
    statement_lines: list[int] = field(default_factory=list)  # body statement starts, for splitting
    members: list[str] = field(default_factory=list)


@dataclass
class Module:
    language: str
    docstring: str | None = None
    doc_lines: tuple[int, int] | None = None
    imports: list[str] = field(default_factory=list)
    import_names: list[str] = field(default_factory=list)
    import_lines: list[int] = field(default_factory=list)
    constants: list[Constant] = field(default_factory=list)
    dataclasses: list[str] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    error_lines: list[int] = field(default_factory=list)
    annotations: list[tuple[int, str]] = field(default_factory=list)


@cache
def parser(language: str):
    from tree_sitter import Language, Parser

    if language == "python":
        import tree_sitter_python as grammar
    elif language == "c":
        import tree_sitter_c as grammar
    elif language == "matlab":
        import tree_sitter_matlab as grammar
    else:
        raise ValueError(f"no grammar for {language}")
    return Parser(Language(grammar.language()))


def unit_from_name(name: str) -> str | None:
    parts = [p for p in re.split(r"_+", name) if p]
    if len(parts) < 2:
        return None
    return UNIT_SUFFIXES.get(parts[-1].casefold())


def units_from_doc(doc: str | None) -> dict[str, str]:
    if not doc:
        return {}
    found = {m.group(1): m.group(2) for m in DOC_UNIT_IN.finditer(doc)}
    for match in DOC_UNIT.finditer(doc):
        found.setdefault(match.group(1), match.group(2))
    return found


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _line(node) -> int:
    return node.start_point[0] + 1


def _end_line(node) -> int:
    row, column = node.end_point
    return row if column == 0 and row > node.start_point[0] else row + 1


def _descendants(node, types: set[str]):
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in types:
            yield current
        stack.extend(reversed(current.children))


def _errors(root) -> list[int]:
    return sorted({_line(n) for n in _descendants(root, {"ERROR"})} | {_line(n) for n in _missing(root)})


def _missing(root):
    stack = [root]
    while stack:
        current = stack.pop()
        if current.is_missing:
            yield current
        stack.extend(current.children)


def _strip_string(literal: str) -> str:
    text = re.sub(r'^[rRbBuUfF]*("""|\'\'\'|"|\')', "", literal.strip())
    return re.sub(r'("""|\'\'\'|"|\')$', "", text).strip()


def _comment_text(comments: list[str]) -> str:
    lines = []
    for comment in comments:
        for line in comment.splitlines():
            line = re.sub(r"^\s*(/\*+|\*+/|\*|//+|%+\{?|%\}|#+)", "", line)
            line = re.sub(r"\*+/\s*$", "", line).rstrip()
            lines.append(line.strip())
    return "\n".join(lines).strip()


def _annotations(root, comment_type: str, out: Module) -> None:
    for node in _descendants(root, {comment_type}):
        for offset, line in enumerate(_text(node).splitlines()):
            match = ANNOTATION.search(line)
            if match:
                out.annotations.append(
                    (_line(node) + offset, f"{match.group(1)}: {match.group(2).strip()}".strip())
                )


def _calls(node, call_type: str, field_name: str) -> list[str]:
    names: list[str] = []
    for call in _descendants(node, {call_type}):
        target = call.child_by_field_name(field_name)
        name = _text(target).replace("self.", "").strip()
        if name and len(name) <= 80 and name not in names:
            names.append(name)
    return names[:50]


def _signature(text: str, stop: str) -> str:
    head = text.split(stop, 1)[0] if stop in text else text.splitlines()[0]
    return re.sub(r"\s+", " ", head).strip()


def _body_groups(statements: list, out: Module, name_prefix: str = "") -> None:
    """Script code: consecutive top-level statements, cut at statement starts every ``BODY_LINES`` lines."""
    group: list = []

    def emit() -> None:
        if not group:
            return
        start, end = _line(group[0]), _end_line(group[-1])
        text = "\n".join(_text(s) for s in group)
        out.symbols.append(
            Symbol(
                qualname=f"{name_prefix}<script lines {start}-{end}>",
                name=f"script lines {start}-{end}",
                kind="body",
                start_line=start,
                end_line=end,
                text=text,
                calls=[],
            )
        )
        group.clear()

    for statement in statements:
        previous = statement.prev_named_sibling
        while previous is not None and previous.type == "comment":
            previous = previous.prev_named_sibling
        if group and (previous != group[-1] or _end_line(statement) - _line(group[0]) >= BODY_LINES):
            emit()  # a definition sits between them, or the group is long enough
        group.append(statement)
    emit()


# ---------------------------------------------------------------- Python


def _py_docstring(block) -> str | None:
    if block is None:
        return None
    first = next((c for c in block.named_children if c.type != "comment"), None)
    if first is not None and first.type == "expression_statement" and first.named_children:
        value = first.named_children[0]
        if value.type in ("string", "concatenated_string"):
            return _strip_string(_text(value))
    return None


def _py_params(node, doc: str | None) -> list[Param]:
    params_node = node.child_by_field_name("parameters")
    doc_units = units_from_doc(doc)
    params = []
    for child in params_node.named_children if params_node is not None else []:
        name_node = child.child_by_field_name("name")
        if child.type == "identifier":
            name = _text(child)
        elif child.type == "typed_parameter":
            name = _text(next((c for c in child.named_children if c.type == "identifier"), None))
        elif name_node is not None:
            name = _text(name_node)
        else:
            name = _text(child)
        if name in ("self", "cls"):
            continue
        type_node = child.child_by_field_name("type")
        value = child.child_by_field_name("value")
        params.append(
            Param(
                name=name,
                annotation=_text(type_node) or None,
                default=_text(value) or None,
                unit=doc_units.get(name.lstrip("*")) or unit_from_name(name.lstrip("*")),
            )
        )
    return params


def _py_function(node, parent: str | None, decorated) -> Symbol:
    name = _text(node.child_by_field_name("name"))
    block = node.child_by_field_name("body")
    doc = _py_docstring(block)
    outer = decorated or node
    return Symbol(
        qualname=f"{parent}.{name}" if parent else name,
        name=name,
        kind="method" if parent else "function",
        start_line=_line(outer),
        end_line=_end_line(outer),
        text=_text(outer),
        signature=_signature(_text(node), ":\n"),
        docstring=doc,
        params=_py_params(node, doc),
        calls=_calls(block, "call", "function") if block is not None else [],
        parent=parent,
        statement_lines=[_line(c) for c in block.named_children] if block is not None else [],
    )


def _is_literal(node, language: str) -> bool:
    if node is None:
        return False
    if node.type in LITERALS[language]:
        return True
    if node.type in ("unary_operator", "list", "tuple", "parenthesized_expression", "matrix", "row"):
        return bool(node.named_children) and all(_is_literal(c, language) for c in node.named_children)
    return False


def parse_python(source: bytes) -> Module:
    tree = parser("python").parse(source)
    root = tree.root_node
    out = Module("python", error_lines=_errors(root))
    _annotations(root, "comment", out)
    statements: list = []
    first_statement = True
    for child in root.named_children:
        node, decorated = child, None
        if child.type == "decorated_definition":
            node, decorated = child.child_by_field_name("definition"), child
        if child.type == "comment":
            if first_statement and out.docstring is None and _line(child) <= 3 and not out.imports:
                continue  # shebang / encoding / licence lines stay in the header text
            continue
        if first_statement and child.type == "expression_statement" and child.named_children:
            value = child.named_children[0]
            if value.type in ("string", "concatenated_string"):
                out.docstring = _strip_string(_text(value))
                out.doc_lines = (_line(child), _end_line(child))
                first_statement = False
                continue
        first_statement = False
        if child.type in ("import_statement", "import_from_statement", "future_import_statement"):
            out.imports.append(_text(child))
            out.import_lines.append(_line(child))
            module = child.child_by_field_name("module_name")
            if module is not None:
                out.import_names.append(_text(module).lstrip(".").split(".")[0] or _text(module))
            else:
                for dotted in child.named_children:
                    target = dotted.child_by_field_name("name") if dotted.type == "aliased_import" else dotted
                    out.import_names.append(_text(target).split(".")[0])
            continue
        if node.type == "function_definition":
            out.symbols.append(_py_function(node, None, decorated))
            continue
        if node.type == "class_definition":
            _py_class(node, decorated, out)
            continue
        if child.type == "expression_statement" and child.named_children:
            assignment = child.named_children[0]
            if assignment.type == "assignment":
                left, right = assignment.child_by_field_name("left"), assignment.child_by_field_name("right")
                if left is not None and left.type == "identifier" and _is_literal(right, "python"):
                    name = _text(left)
                    out.constants.append(Constant(name, _text(right), _line(child), unit_from_name(name)))
        statements.append(child)
    _body_groups(statements, out)
    out.import_names = list(dict.fromkeys(n for n in out.import_names if n))
    out.symbols.sort(key=lambda s: s.start_line)
    return out


def _py_class(node, decorated, out: Module) -> None:
    name = _text(node.child_by_field_name("name"))
    block = node.child_by_field_name("body")
    doc = _py_docstring(block)
    outer = decorated or node
    decorators = (
        "\n".join(_text(d) for d in decorated.named_children if d.type == "decorator") if decorated else ""
    )
    attributes, methods, init_assignments = [], [], []
    for child in block.named_children if block is not None else []:
        inner, inner_decorated = child, None
        if child.type == "decorated_definition":
            inner, inner_decorated = child.child_by_field_name("definition"), child
        if inner.type == "function_definition":
            method = _py_function(inner, name, inner_decorated)
            methods.append(method)
            if method.name == "__init__":
                for assignment in _descendants(inner, {"assignment"}):
                    left = assignment.child_by_field_name("left")
                    if left is not None and _text(left).startswith("self."):
                        init_assignments.append(_text(assignment).splitlines()[0][:160])
        elif child.type == "expression_statement" and child.named_children:
            if child.named_children[0].type == "assignment":
                attributes.append(_text(child).splitlines()[0][:160])
    signature = _signature(_text(node), ":\n")
    preamble = [decorators.strip(), signature + ":"] if decorators.strip() else [signature + ":"]
    if doc:
        preamble.append(f'    """{doc.splitlines()[0]}"""')
    preamble += [f"    {a}" for a in attributes] + [f"    # __init__: {a}" for a in init_assignments]
    class_symbol = Symbol(
        qualname=name,
        name=name,
        kind="class",
        start_line=_line(outer),
        end_line=_end_line(outer),
        text="\n".join(preamble),
        signature=signature,
        docstring=doc,
        members=[m.name for m in methods],
    )
    out.symbols.append(class_symbol)
    if "dataclass" in decorators:
        fields = [a.split("=")[0].strip() for a in attributes]
        out.dataclasses.append(f"{name}({', '.join(fields)})")
    for method in methods:
        method.preamble = "\n".join(preamble)
        out.symbols.append(method)


# ---------------------------------------------------------------- C


def _c_name(declarator) -> str:
    """The identifier inside a declarator (through pointer, array and function declarators)."""
    node = declarator
    while node is not None and node.child_by_field_name("declarator") is not None:
        node = node.child_by_field_name("declarator")
    return _text(node)


def _leading_comment(node) -> str | None:
    comments, previous, expected = [], node.prev_named_sibling, _line(node)
    while previous is not None and previous.type == "comment" and _end_line(previous) >= expected - 2:
        comments.insert(0, _text(previous))
        expected = _line(previous)
        previous = previous.prev_named_sibling
    return _comment_text(comments) or None


def parse_c(source: bytes) -> Module:
    tree = parser("c").parse(source)
    root = tree.root_node
    out = Module("c", error_lines=_errors(root))
    _annotations(root, "comment", out)
    children = root.named_children
    leading = []
    for child in children:
        if child.type != "comment":
            break
        leading.append(child)
    if leading:
        out.docstring = _comment_text([_text(c) for c in leading])
        out.doc_lines = (_line(leading[0]), _end_line(leading[-1]))
    statements: list = []
    for child in children[len(leading) :]:
        kind = child.type
        if kind == "comment":
            continue
        if kind in ("preproc_include",):
            out.imports.append(_text(child).strip())
            out.import_lines.append(_line(child))
            out.import_names.append(_text(child.child_by_field_name("path")).strip('"<>'))
        elif kind == "preproc_def":
            name, value = (
                _text(child.child_by_field_name("name")),
                _text(child.child_by_field_name("value")).strip(),
            )
            out.constants.append(Constant(name, value, _line(child), unit_from_name(name)))
        elif kind == "function_definition":
            name = _c_name(child.child_by_field_name("declarator"))
            body = child.child_by_field_name("body")
            doc = _leading_comment(child)
            params = []
            function = child.child_by_field_name("declarator")
            while function is not None and function.type != "function_declarator":
                function = function.child_by_field_name("declarator")
            plist = function.child_by_field_name("parameters") if function is not None else None
            for p in plist.named_children if plist is not None else []:
                if p.type == "parameter_declaration":
                    pname = (
                        _c_name(p.child_by_field_name("declarator"))
                        if p.child_by_field_name("declarator")
                        else ""
                    )
                    params.append(
                        Param(pname or _text(p), annotation=_text(p.child_by_field_name("type")) or None)
                    )
            for param in params:
                param.unit = units_from_doc(doc).get(param.name) or unit_from_name(param.name)
            out.symbols.append(
                Symbol(
                    qualname=name,
                    name=name,
                    kind="function",
                    start_line=_line(child),
                    end_line=_end_line(child),
                    text=_text(child),
                    signature=_signature(_text(child), "{"),
                    docstring=doc,
                    params=params,
                    calls=_calls(body, "call_expression", "function") if body is not None else [],
                    statement_lines=[_line(c) for c in body.named_children] if body is not None else [],
                )
            )
        elif kind in ("struct_specifier", "enum_specifier", "union_specifier", "type_definition") or (
            kind == "declaration"
            and any(
                c.type in ("struct_specifier", "enum_specifier") and c.child_by_field_name("body")
                for c in child.named_children
            )
        ):
            name_node = child.child_by_field_name("name") or child.child_by_field_name("declarator")
            name = _text(name_node) or _text(
                next(
                    (
                        c.child_by_field_name("name")
                        for c in child.named_children
                        if c.child_by_field_name("name")
                    ),
                    None,
                )
            )
            name = name or f"type@{_line(child)}"
            out.symbols.append(
                Symbol(
                    qualname=name,
                    name=name,
                    kind="type",
                    start_line=_line(child),
                    end_line=_end_line(child),
                    text=_text(child),
                    signature=_signature(_text(child), "{"),
                    docstring=_leading_comment(child),
                )
            )
        else:
            if kind == "declaration":
                value = child.child_by_field_name("declarator")
                if (
                    value is not None
                    and value.type == "init_declarator"
                    and _is_literal(value.child_by_field_name("value"), "c")
                ):
                    name = _c_name(value.child_by_field_name("declarator"))
                    out.constants.append(
                        Constant(
                            name,
                            _text(value.child_by_field_name("value")),
                            _line(child),
                            unit_from_name(name),
                        )
                    )
            statements.append(child)
    _body_groups(statements, out)
    out.symbols.sort(key=lambda s: s.start_line)
    return out


# ---------------------------------------------------------------- MATLAB


def _matlab_function(node, parent: str | None) -> Symbol:
    name = _text(node.child_by_field_name("name"))
    comments, statements = [], []
    arguments = []
    for child in node.named_children:
        if child.type == "comment" and not statements:
            comments.append(_text(child))
        elif child.type == "arguments_statement":
            arguments.append(_text(child))
        elif child.type == "block":
            statements = child.named_children
    doc = _comment_text(comments) or None
    params = []
    args_node = next((c for c in node.named_children if c.type == "function_arguments"), None)
    doc_units = units_from_doc(doc)
    for ident in args_node.named_children if args_node is not None else []:
        pname = _text(ident)
        if pname in ("obj", "self"):
            continue
        params.append(Param(pname, unit=doc_units.get(pname) or unit_from_name(pname)))
    for block in arguments:
        for line in block.splitlines()[1:-1]:
            parts = line.strip().split(None, 1)
            for param in params:
                if parts and parts[0] == param.name and len(parts) > 1:
                    param.annotation = parts[1].split("=")[0].strip()
                    if "=" in parts[1]:
                        param.default = parts[1].split("=", 1)[1].strip().rstrip(";")
    return Symbol(
        qualname=f"{parent}.{name}" if parent else name,
        name=name,
        kind="method" if parent else "function",
        start_line=_line(node),
        end_line=_end_line(node),
        text=_text(node),
        signature=_text(node).splitlines()[0].strip(),
        docstring=doc,
        params=params,
        calls=[],
        parent=parent,
        statement_lines=[_line(s) for s in statements],
    )


def parse_matlab(source: bytes) -> Module:
    tree = parser("matlab").parse(source)
    root = tree.root_node
    out = Module("matlab", error_lines=_errors(root))
    _annotations(root, "comment", out)
    children = root.named_children
    leading = []
    for child in children:
        if child.type != "comment":
            break
        leading.append(child)
    if leading:
        out.docstring = _comment_text([_text(c) for c in leading])
        out.doc_lines = (_line(leading[0]), _end_line(leading[-1]))
    statements = []
    for child in children[len(leading) :]:
        if child.type == "function_definition":
            out.symbols.append(_matlab_function(child, None))
        elif child.type == "class_definition":
            name = _text(child.child_by_field_name("name"))
            preamble = [_text(child).splitlines()[0]]
            methods = []
            for part in child.named_children:
                if part.type == "comment" and not methods:
                    preamble.append(_text(part))
                elif part.type == "properties":
                    preamble.append(_text(part))
                elif part.type == "methods":
                    for function in part.named_children:
                        if function.type == "function_definition":
                            methods.append(_matlab_function(function, name))
            text = "\n".join(preamble)
            out.symbols.append(
                Symbol(
                    qualname=name,
                    name=name,
                    kind="class",
                    start_line=_line(child),
                    end_line=_end_line(child),
                    text=text,
                    signature=preamble[0].strip(),
                    docstring=_comment_text([p for p in preamble[1:] if p.lstrip().startswith("%")]) or None,
                    members=[m.name for m in methods],
                )
            )
            for method in methods:
                method.preamble = text
                out.symbols.append(method)
        elif child.type == "comment":
            continue
        else:
            if child.type == "assignment":
                left, right = child.child_by_field_name("left"), child.child_by_field_name("right")
                if left is not None and left.type == "identifier" and _is_literal(right, "matlab"):
                    name = _text(left)
                    out.constants.append(Constant(name, _text(right), _line(child), unit_from_name(name)))
            statements.append(child)
    _body_groups(statements, out)
    out.symbols.sort(key=lambda s: s.start_line)
    return out


PARSERS = {"python": parse_python, "c": parse_c, "matlab": parse_matlab}
