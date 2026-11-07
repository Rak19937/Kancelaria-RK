"""Text extraction for document formats readable with the Python stdlib.

Accepted attachments that cannot be reliably transcribed are preserved, not
presented as analysed legal documents (e.g. legacy .doc, sound and video).
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from email.parser import BytesParser
from email.policy import default as email_policy

MAX_XML = 8 * 1024 * 1024
MAX_OUTPUT = 350_000


def xml_member(data: bytes, member: str):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info=z.getinfo(member)
        if info.file_size>MAX_XML:
            raise ValueError('Za duży element XML dokumentu do analizy.')
        with z.open(info) as f:
            payload=f.read(MAX_XML+1)
    if len(payload)>MAX_XML:
        raise ValueError('Przekroczono limit ekstrakcji XML.')
    return ET.fromstring(payload)


def extract_extra_text(filename: str, data: bytes) -> tuple[str,int,str,str]:
    ext=filename.lower().rsplit('.',1)[-1] if '.' in filename else ''
    if ext in {'odt','ods'}:
        root=xml_member(data,'content.xml')
        prefix='{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'
        text='\n'.join(''.join(node.itertext()).strip() for node in root.iter()
                       if node.tag in (prefix+'p',prefix+'h'))
        return text[:MAX_OUTPUT],0,'tekst_fragment',''
    if ext=='pptx':
        prefix='{http://schemas.openxmlformats.org/drawingml/2006/main}'
        parts=[]
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            slides=sorted((i.filename for i in z.infolist()
                         if re.fullmatch(r'ppt/slides/slide\d+\.xml',i.filename)),
                         key=lambda s:int(re.search(r'\d+',s).group()))[:60]
        for slide in slides:
            root=xml_member(data,slide)
            parts.append('\n'.join(e.text or '' for e in root.iter() if e.tag==prefix+'t'))
        return '\n\n'.join(parts)[:MAX_OUTPUT],0,'tekst_fragment',''
    if ext=='eml':
        msg=BytesParser(policy=email_policy).parsebytes(data[:8*1024*1024])
        chunks=[str(msg.get('Subject') or ''),str(msg.get('From') or ''),str(msg.get('Date') or '')]
        for part in msg.walk():
            if part.get_content_type() != 'text/plain' or part.get_content_disposition()=='attachment':
                continue
            try:chunks.append(str(part.get_content()))
            except Exception:pass
        return '\n'.join(chunks)[:MAX_OUTPUT],0,'tekst_fragment',''
    return '',0,'bez_odczytu_formatu',''
