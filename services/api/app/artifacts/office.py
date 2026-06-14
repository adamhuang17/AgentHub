from __future__ import annotations

from html import unescape
from io import BytesIO
import re
from typing import Iterable
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
OFFICE_ARTIFACT_TYPES = {"word_doc", "presentation"}
OFFICE_MIME_TYPES = {DOCX_MIME_TYPE, PPTX_MIME_TYPE}


def render_office_artifact(
    *,
    artifact_type: str,
    title: str,
    mime_type: str,
    content_text: str,
) -> tuple[str, str, bytes | str]:
    if artifact_type == "word_doc" or mime_type == DOCX_MIME_TYPE:
        clean_title = _ensure_extension(title, ".docx")
        return clean_title, DOCX_MIME_TYPE, render_docx(content_text, title=_display_title(clean_title))
    if artifact_type == "presentation" or mime_type == PPTX_MIME_TYPE:
        clean_title = _ensure_extension(title, ".pptx")
        return clean_title, PPTX_MIME_TYPE, render_pptx(content_text, title=_display_title(clean_title))
    return title, mime_type, content_text


def render_docx(content_text: str, *, title: str) -> bytes:
    paragraphs = list(_markdown_blocks(content_text, fallback_title=title))
    body = "\n".join(_docx_paragraph(block) for block in paragraphs)
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    return _zip_bytes(
        {
            "[Content_Types].xml": content_types,
            "_rels/.rels": rels,
            "word/document.xml": document_xml,
        }
    )


def render_pptx(content_text: str, *, title: str) -> bytes:
    slides = _slides_from_markdown(content_text, fallback_title=title)
    slide_count = max(1, len(slides))
    overrides = "\n".join(
        f'  <Override PartName="/ppt/slides/slide{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for index in range(1, slide_count + 1)
    )
    content_types = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
{overrides}
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
</Types>
"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>
"""
    slide_ids = "\n".join(
        f'    <p:sldId id="{255 + index}" r:id="rId{index}"/>'
        for index in range(1, slide_count + 1)
    )
    pres_rels = "\n".join(
        f'  <Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{index}.xml"/>'
        for index in range(1, slide_count + 1)
    )
    presentation_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId{slide_count + 1}"/></p:sldMasterIdLst>
  <p:sldIdLst>
{slide_ids}
  </p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000" type="screen16x9"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>
"""
    presentation_rels_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{pres_rels}
  <Relationship Id="rId{slide_count + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
</Relationships>
"""
    files: dict[str, str] = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": root_rels,
        "ppt/presentation.xml": presentation_xml,
        "ppt/_rels/presentation.xml.rels": presentation_rels_xml,
        "ppt/slideMasters/slideMaster1.xml": _slide_master_xml(),
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _slide_master_rels_xml(),
        "ppt/slideLayouts/slideLayout1.xml": _slide_layout_xml(),
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _slide_layout_rels_xml(),
        "ppt/theme/theme1.xml": _theme_xml(),
    }
    for index, slide in enumerate(slides, start=1):
        files[f"ppt/slides/slide{index}.xml"] = _slide_xml(
            slide["title"],
            slide["body"],
            slide_number=index,
        )
        files[f"ppt/slides/_rels/slide{index}.xml.rels"] = _slide_rels_xml()
    return _zip_bytes(files)


def extract_office_text(raw: bytes, *, artifact_type: str, mime_type: str) -> str:
    try:
        with ZipFile(BytesIO(raw), "r") as archive:
            if artifact_type == "word_doc" or mime_type == DOCX_MIME_TYPE:
                return _xml_text(archive.read("word/document.xml").decode("utf-8", errors="replace"))
            if artifact_type == "presentation" or mime_type == PPTX_MIME_TYPE:
                names = sorted(name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name))
                chunks = []
                for index, name in enumerate(names, start=1):
                    text = _xml_text(archive.read(name).decode("utf-8", errors="replace"))
                    if text:
                        chunks.append(f"Slide {index}\n{text}")
                return "\n\n".join(chunks)
    except Exception:
        return ""
    return ""


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))
    return buffer.getvalue()


def _markdown_blocks(text: str, *, fallback_title: str) -> Iterable[tuple[str, str]]:
    clean = text.strip()
    if not clean:
        yield "title", fallback_title
        return
    for raw_line in clean.splitlines():
        line = raw_line.strip()
        if not line:
            yield "space", ""
            continue
        if line.startswith("# "):
            yield "title", line[2:].strip()
        elif line.startswith("## "):
            yield "heading", line[3:].strip()
        elif line.startswith(("- ", "* ")):
            yield "bullet", line[2:].strip()
        else:
            yield "body", line


def _docx_paragraph(block: tuple[str, str]) -> str:
    kind, text = block
    if kind == "space":
        return "<w:p/>"
    size = "36" if kind == "title" else "28" if kind == "heading" else "22"
    bold = "<w:b/>" if kind in {"title", "heading"} else ""
    prefix = "• " if kind == "bullet" else ""
    return (
        "<w:p>"
        "<w:r>"
        f"<w:rPr>{bold}<w:sz w:val=\"{size}\"/></w:rPr>"
        f"<w:t xml:space=\"preserve\">{escape(prefix + text)}</w:t>"
        "</w:r>"
        "</w:p>"
    )


def _slides_from_markdown(text: str, *, fallback_title: str) -> list[dict[str, list[str] | str]]:
    slides: list[dict[str, list[str] | str]] = []
    current_title = fallback_title
    current_body: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if current_body or slides:
                slides.append({"title": current_title, "body": current_body})
                current_body = []
            current_title = line.lstrip("#").strip() or fallback_title
        elif line.startswith(("- ", "* ")):
            current_body.append(line[2:].strip())
        else:
            current_body.append(line)
        if len(current_body) >= 6:
            slides.append({"title": current_title, "body": current_body})
            current_title = "Next Steps"
            current_body = []
    if current_body or not slides:
        slides.append({"title": current_title, "body": current_body or ["Generated by AgentHub."]})
    return slides[:12]


def _slide_xml(title: str, body: list[str] | str, *, slide_number: int) -> str:
    body_lines = body if isinstance(body, list) else [body]
    body_paragraphs = "\n".join(_ppt_text_paragraph(line, bullet=True) for line in body_lines[:7])
    accent = "0F766E" if slide_number % 2 else "2563EB"
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:bg><p:bgPr><a:solidFill><a:srgbClr val="F8FAFC"/></a:solidFill></p:bgPr></p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr><a:xfrm><a:off x="685800" y="548640"/><a:ext cx="10820400" cy="914400"/></a:xfrm></p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/>{_ppt_text_paragraph(title, size="3600", color=accent)}</p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="3" name="Body"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr><a:xfrm><a:off x="914400" y="1645920"/><a:ext cx="10363200" cy="4206240"/></a:xfrm></p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/>{body_paragraphs}</p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
"""


def _ppt_text_paragraph(text: str, *, bullet: bool = False, size: str = "2200", color: str = "1F2937") -> str:
    bullet_xml = '<a:buChar char="•"/>' if bullet else "<a:buNone/>"
    return (
        f'<a:p><a:pPr>{bullet_xml}</a:pPr><a:r><a:rPr lang="en-US" sz="{size}">'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:rPr>'
        f"<a:t>{escape(text)}</a:t></a:r></a:p>"
    )


def _slide_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>
"""


def _slide_master_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>
"""


def _slide_master_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>
"""


def _slide_layout_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
  <p:cSld name="AgentHub Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>
"""


def _slide_layout_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>
"""


def _theme_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="AgentHub">
  <a:themeElements>
    <a:clrScheme name="AgentHub"><a:dk1><a:srgbClr val="111827"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="0F766E"/></a:dk2><a:lt2><a:srgbClr val="F8FAFC"/></a:lt2><a:accent1><a:srgbClr val="0F766E"/></a:accent1><a:accent2><a:srgbClr val="2563EB"/></a:accent2><a:accent3><a:srgbClr val="F59E0B"/></a:accent3><a:accent4><a:srgbClr val="DC2626"/></a:accent4><a:accent5><a:srgbClr val="7C3AED"/></a:accent5><a:accent6><a:srgbClr val="0891B2"/></a:accent6><a:hlink><a:srgbClr val="2563EB"/></a:hlink><a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink></a:clrScheme>
    <a:fontScheme name="AgentHub"><a:majorFont><a:latin typeface="Aptos Display"/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/></a:minorFont></a:fontScheme>
    <a:fmtScheme name="AgentHub"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme>
  </a:themeElements>
</a:theme>
"""


def _xml_text(xml: str) -> str:
    values = re.findall(r"<(?:w|a):t[^>]*>(.*?)</(?:w|a):t>", xml, flags=re.DOTALL)
    return "\n".join(unescape(re.sub(r"\s+", " ", value)).strip() for value in values if value.strip()).strip()


def _ensure_extension(title: str, extension: str) -> str:
    clean = title.strip() or f"AgentHub Artifact{extension}"
    return clean if clean.lower().endswith(extension) else f"{clean}{extension}"


def _display_title(filename: str) -> str:
    return re.sub(r"\.(docx|pptx)$", "", filename, flags=re.IGNORECASE).strip() or "AgentHub Artifact"
