"""Synthetic PDFs made entirely from test strings; no external fonts/documents."""

import hashlib
from io import BytesIO
from uuid import UUID

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from packages.domain.extraction import DocumentSource


def syllabus_pdf(pages: list[str], *, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    characters = sorted(set("".join(pages)) - {"\n", "\r"})
    assert len(characters) < 255
    codes = {character: index for index, character in enumerate(characters, 1)}
    cmap = DecodedStreamObject()
    mapping = "\n".join(f"<{code:02x}> <{char.encode('utf-16-be').hex()}>"
                        for char, code in codes.items())
    cmap.set_data(("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
                   "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
                   "/CMapName /Synthetic def\n/CMapType 2 def\n1 begincodespacerange\n"
                   "<00> <ff>\nendcodespacerange\n"
                   f"{len(codes)} beginbfchar\n{mapping}\nendbfchar\n"
                   "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend").encode())
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"), NameObject("/ToUnicode"): cmap,
    })
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        operations = ["BT /F1 12 Tf 14 TL 36 750 Td"]
        for line in text.split("\n"):
            data = bytes(codes[c] for c in line).hex()
            operations.append(f"<{data}> Tj T*")
        operations.append("ET")
        stream.set_data("\n".join(operations).encode())
        page[NameObject("/Contents")] = stream
    if encrypted:
        writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def document_source(content: bytes, page_count: int) -> DocumentSource:
    return DocumentSource(course_id=UUID(int=1), document_id=UUID(int=2), version_id=UUID(int=3),
                          version_number=1, sha256=hashlib.sha256(content).hexdigest(),
                          size_bytes=len(content), page_count=page_count)
