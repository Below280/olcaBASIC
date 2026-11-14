"""
The EPD document as a Word file (.docx), written with the standard
library only: EPD DOCUMENT renders Markdown, and this turns that
Markdown (headings, paragraphs, bold, bullet lists, tables, pictures and
the draft notice) into WordprocessingML. The file opens in Word,
LibreOffice and Google Docs, where the EPD owner's own layout can be
applied.
"""

import os
import re
import struct
import zipfile
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

EMU_PER_CM = 360000
MAX_WIDTH_CM = 15.0

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Default Extension="gif" ContentType="image/gif"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>{title}</dc:title><dc:creator>olcaBASIC</dc:creator>
</cp:coreProperties>"""


def _heading_style(level: int, size: int) -> str:
    return (f'<w:style w:type="paragraph" w:styleId="Heading{level}">'
            f'<w:name w:val="heading {level}"/><w:basedOn w:val="Normal"/>'
            f'<w:next w:val="Normal"/><w:qFormat/>'
            f'<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/>'
            f'<w:outlineLvl w:val="{level - 1}"/></w:pPr>'
            f'<w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>')


STYLES = ("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="20"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="240"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>
""" + _heading_style(1, 32) + _heading_style(2, 28) + _heading_style(3, 24)
          + _heading_style(4, 22) + """
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Notice"><w:name w:val="Notice"/><w:basedOn w:val="Normal"/><w:pPr><w:pBdr><w:top w:val="single" w:sz="8" w:space="4" w:color="C00000"/><w:bottom w:val="single" w:sz="8" w:space="4" w:color="C00000"/></w:pBdr></w:pPr><w:rPr><w:color w:val="C00000"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="Grid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:left w:val="single" w:sz="4" w:space="0" w:color="808080"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:right w:val="single" w:sz="4" w:space="0" w:color="808080"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="808080"/>
</w:tblBorders><w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>""")

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')

IMAGE = re.compile(r"^!\[(.*?)\]\((.+)\)\s*$")
BOLD = re.compile(r"\*\*(.+?)\*\*")


def image_size(path: str) -> Optional[Tuple[int, int]]:
    """(width, height) in pixels of a PNG, GIF or JPEG, or None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
            if head[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    marker = fh.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    size = struct.unpack(">H", fh.read(2))[0]
                    if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (
                            0xC4, 0xC8, 0xCC):
                        h, w = struct.unpack(">xHH", fh.read(5))
                        return w, h
                    fh.seek(size - 2, 1)
    except (OSError, struct.error):
        return None
    return None


def _runs(text: str) -> str:
    """Text with **bold** parts, as runs."""
    out = []
    pos = 0
    for m in BOLD.finditer(text):
        if m.start() > pos:
            out.append(_run(text[pos:m.start()]))
        out.append(_run(m.group(1), bold=True))
        pos = m.end()
    if pos < len(text):
        out.append(_run(text[pos:]))
    return "".join(out) or _run("")


def _run(text: str, bold: bool = False, small: bool = False) -> str:
    props = ("<w:b/>" if bold else "") + ('<w:sz w:val="16"/>' if small
                                         else "")
    props = f"<w:rPr>{props}</w:rPr>" if props else ""
    return (f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t>'
            f'</w:r>')


def _para(text: str, style: str = "") -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_runs(text)}</w:p>"


WIDE = 6        # a table with more columns than this is a results table


def _table(rows: List[List[str]], header: bool) -> str:
    cols = max(len(r) for r in rows)
    page = int(MAX_WIDTH_CM * 567)                       # twips
    wide = cols > WIDE
    if wide:
        first = int(2.4 * 567)
        widths = [first] + [int((page - first) / (cols - 1))] * (cols - 1)
    else:
        widths = [int(page / cols)] * cols
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    xml = [f'<w:tbl><w:tblPr><w:tblStyle w:val="Grid"/>'
           f'<w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
           f'<w:tblLayout w:type="fixed"/></w:tblPr>'
           f'<w:tblGrid>{grid}</w:tblGrid>']
    for n, row in enumerate(rows):
        bold = header and n == 0
        head = "<w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>" if bold \
            else "<w:trPr><w:cantSplit/></w:trPr>"
        xml.append(f"<w:tr>{head}")
        for c in range(cols):
            text = row[c] if c < len(row) else ""
            no_wrap = "<w:noWrap/>" if wide and c > 0 and not bold else ""
            body = (f"<w:p>{_run(text, bold=bold, small=wide)}</w:p>"
                    if bold or wide else f"<w:p>{_runs(text)}</w:p>")
            xml.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[c]}" '
                       f'w:type="dxa"/>{no_wrap}</w:tcPr>{body}</w:tc>')
        xml.append("</w:tr>")
    xml.append("</w:tbl><w:p/>")
    return "".join(xml)


def _picture(rid: str, n: int, name: str, size: Tuple[int, int]) -> str:
    w_px, h_px = size
    width_cm = min(MAX_WIDTH_CM, w_px / 96 * 2.54) if w_px else MAX_WIDTH_CM
    cx = int(width_cm * EMU_PER_CM)
    cy = int(cx * h_px / w_px) if w_px else int(cx * 0.6)
    alt = escape(name, {'"': "&quot;"})
    return (f'<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" '
            f'distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{n}" name="Picture {n}" descr="{alt}"/>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{n}" name="Picture {n}"/>'
            f'<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>'
            f'<a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
            f'</pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect">'
            f'<a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData>'
            f'</a:graphic></wp:inline></w:drawing></w:r></w:p>')


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown_to_docx(markdown: str, path: str, title: str = "") -> List[str]:
    """Write the Markdown of EPD DOCUMENT as a .docx file. Returns the
    pictures that could not be embedded (missing or of an unknown
    format); each is left in the text as its file name."""
    body: List[str] = []
    media: List[Tuple[str, str, bytes]] = []    # (rid, part name, data)
    skipped: List[str] = []
    lines = markdown.split("\n")
    i = 0
    first_heading = True
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            rows = [_cells(r) for r in block
                    if not re.match(r"^\|(\s*-+\s*\|)+\s*$", r.replace(
                        "---", "-"))]
            header = any(c for c in rows[0])
            if not header:
                rows = rows[1:]
            if rows:
                body.append(_table(rows, header))
            continue
        m = re.match(r"^(#{1,4}) (.*)$", line)
        if m:
            level = len(m.group(1))
            style = "Title" if level == 1 and first_heading \
                else f"Heading{level}"
            first_heading = False
            body.append(_para(m.group(2), style))
            i += 1
            continue
        m = IMAGE.match(line)
        if m:
            alt, file = m.group(1), m.group(2)
            ext = os.path.splitext(file)[1].lower().lstrip(".")
            size = image_size(file) if ext in ("png", "jpg", "jpeg",
                                               "gif") else None
            if size is None:
                skipped.append(file)
                body.append(_para(f"[{alt}: {file}]"))
            else:
                rid = f"rIdImage{len(media) + 1}"
                part = f"media/image{len(media) + 1}.{ext}"
                with open(file, "rb") as fh:
                    media.append((rid, part, fh.read()))
                body.append(_picture(rid, len(media), alt, size))
            i += 1
            continue
        if line.startswith("> "):
            body.append(_para(line[2:], "Notice"))
            i += 1
            continue
        if line.startswith("- "):
            body.append(_para("•\t" + line[2:], "ListBullet"))
            i += 1
            continue
        text = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#|\||!\[|> |- )", lines[i]):
            text.append(lines[i])
            i += 1
        body.append(_para(" ".join(t.strip() for t in text)))

    section = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
               '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
               'w:left="1134" w:header="567" w:footer="567" w:gutter="0"/>'
               '</w:sectPr>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document {NS}><w:body>{"".join(body)}{section}'
                f'</w:body></w:document>')
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships">'
            '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats'
            '.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>']
    for rid, part, _ in media:
        rels.append(f'<Relationship Id="{rid}" Type="http://schemas.'
                    f'openxmlformats.org/officeDocument/2006/relationships/'
                    f'image" Target="{part}"/>')
    rels.append("</Relationships>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("docProps/core.xml",
                   CORE.format(title=escape(title or "EPD")))
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/_rels/document.xml.rels", "".join(rels))
        for _, part, data in media:
            z.writestr(f"word/{part}", data)
    return skipped
