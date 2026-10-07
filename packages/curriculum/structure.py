"""Pure conservative syllabus heading heuristics. Scores are rules, not probabilities."""

import re

from packages.domain.extraction import (
    DetectionMethod,
    DocumentSource,
    ExtractedPage,
    ExtractionWarning,
    NodeType,
    SourceReference,
    StructureNode,
    WarningCode,
    node_id,
)

_KEYWORD = re.compile(
    r"^(Module|Unit|Chapter|Section|Topic)\s+(\d+(?:\.\d+)*|[IVXLCDM]+)"
    r"(?:(?:\s*[:.\-–—]\s*|\s+)(.*))?$", re.IGNORECASE,
)
_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)(?:[.)]\s+|\s+)(\S.*)$")
_ROMAN = re.compile(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_COMMON = frozenset({
    "course objectives", "learning objectives", "learning outcomes", "course outcomes",
    "course content", "syllabus", "prerequisites", "assessment", "assessment methods",
    "textbooks", "references", "recommended reading", "course description",
})


def _heading_shape(line: str) -> bool:
    return (0 < len(line) <= 120 and len(line.split()) <= 14
            and not line.endswith((".", ";", "?", "!")) and "  " not in line)


def detect_structure(
    source: DocumentSource, pages: list[ExtractedPage],
) -> tuple[list[StructureNode], list[SourceReference], list[ExtractionWarning]]:
    lines = [(page.number, n, line) for page in pages
             for n, line in enumerate(page.text.split("\n"), 1)]
    caps = {line.strip() for i, (_, _, line) in enumerate(lines)
            if _heading_shape(line.strip()) and line.strip().isupper()
            and len(line.split()) >= 2 and (i == 0 or not lines[i - 1][2].strip())
            and (i + 1 == len(lines) or not lines[i + 1][2].strip())}
    nodes: list[StructureNode] = []
    unclassified: list[SourceReference] = []
    warnings: list[ExtractionWarning] = []
    stack: list[StructureNode] = []
    numbered: dict[str, StructureNode] = {}
    ranks = {kind: rank for rank, kind in enumerate(NodeType)}
    for index, (page, n, raw) in enumerate(lines):
        title = raw.strip()
        if not title:
            continue
        ref = SourceReference(page=page, line_start=n, line_end=n)
        kind: NodeType | None = None
        number = ""
        method: DetectionMethod = "keyword_number"
        confidence = 0.98
        keyword, decimal = _KEYWORD.fullmatch(title), _NUMBER.fullmatch(title)
        if _heading_shape(title):
            if keyword and (keyword[2][0].isdigit() or _ROMAN.fullmatch(keyword[2].upper())):
                kind = NodeType(keyword[1].upper())
                number = keyword[2]
            elif decimal and decimal[2][0].isupper() and all(
                0 < int(part) < 100 for part in decimal[1].split(".")
            ):
                number = decimal[1]
                parent_number = numbered.get(number.rpartition(".")[0])
                depth = len(number.split("."))
                if parent_number and parent_number.type in {NodeType.TOPIC, NodeType.SUBTOPIC}:
                    kind = NodeType.SUBTOPIC
                else:
                    kind = (NodeType.TOPIC if depth in {1, 3} else
                            NodeType.SECTION if depth == 2 else NodeType.SUBTOPIC)
                method, confidence = "decimal_number", 0.9 if parent_number else 0.8
            elif title.lower().rstrip(":") in _COMMON:
                kind, method, confidence = NodeType.SECTION, "syllabus_heading", 0.85
            elif title in caps and len(caps) >= 2 and (
                index == 0 or not lines[index - 1][2].strip()
            ) and (index + 1 == len(lines) or not lines[index + 1][2].strip()):
                kind, method, confidence = NodeType.SECTION, "repeated_caps", 0.65
        if kind is None:
            if keyword or decimal:
                warnings.append(ExtractionWarning(code=WarningCode.AMBIGUOUS_HEADING,
                                                  page=page, source=ref))
            if unclassified and unclassified[-1].page == page and (
                unclassified[-1].line_end == n - 1
            ):
                unclassified[-1] = SourceReference(page=page,
                                                   line_start=unclassified[-1].line_start,
                                                   line_end=n)
            else:
                unclassified.append(ref)
            continue
        if kind in {NodeType.MODULE, NodeType.UNIT, NodeType.CHAPTER}:
            numbered.clear()
        numeric_parent = numbered.get(number.rpartition(".")[0]) if "." in number else None
        while stack and ranks[stack[-1].type] >= ranks[kind]:
            stack.pop()
        parent = numeric_parent or (stack[-1] if stack else None)
        if parent and ranks[parent.type] > ranks[kind]:
            parent = stack[-1] if stack else None
        node = StructureNode(
            id=node_id(source, kind, ref, title), type=kind, title=title,
            parent_id=parent.id if parent else None, order=len(nodes) + 1, source=ref,
            detection_method=method, parse_confidence=confidence,
        )
        nodes.append(node)
        stack.append(node)
        if number:
            numbered = {key: value for key, value in numbered.items()
                        if not key.startswith(number + ".")}
            numbered[number] = node
    return nodes, unclassified, warnings
