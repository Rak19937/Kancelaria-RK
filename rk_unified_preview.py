# -*- coding: utf-8 -*-
"""Lokalny, bezpieczny podgląd załączników RK KANCELARIA.

Nie wysyła plików na serwery zewnętrzne, nie wykonuje makr/HTML z dokumentów.
Dokumenty Word/ODT są renderowane do uproszczonego, bezpiecznego HTML.
Wersja 0.3.3-dev1.
"""
from __future__ import annotations

import email
import html
import io
import json
import mimetypes
import re
import shutil
import zipfile
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

IMAGE = {'.jpg','.jpeg','.png','.gif','.webp','.bmp','.tif','.tiff'}
IMAGE_NATIVE = {'.jpg','.jpeg','.png','.gif','.webp','.bmp'}
AUDIO = {'.mp3','.wav','.ogg','.oga','.m4a','.aac','.flac','.opus','.wma'}
VIDEO = {'.mp4','.m4v','.webm','.mov','.avi','.mkv','.wmv','.mpeg','.mpg'}
TEXT = {'.txt','.md','.csv','.tsv','.log','.json','.xml','.yaml','.yml','.ini','.eml','.html','.htm','.css','.py'}
OFFICE = {'.docx','.xlsx','.xlsm','.odt','.ods','.pptx','.rtf'}
SUPPORTED = IMAGE | AUDIO | VIDEO | TEXT | OFFICE | {'.pdf','.zip'}
MIME = {'.mp3':'audio/mpeg','.m4a':'audio/mp4','.aac':'audio/aac','.flac':'audio/flac',
        '.opus':'audio/ogg','.oga':'audio/ogg','.wma':'application/octet-stream',
        '.mp4':'video/mp4','.m4v':'video/mp4','.mov':'video/quicktime',
        '.avi':'video/x-msvideo','.mkv':'video/x-matroska','.wmv':'application/octet-stream',
        '.webm':'video/webm','.mpeg':'video/mpeg','.mpg':'video/mpeg',
        '.tif':'application/octet-stream','.tiff':'application/octet-stream'}
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
ODT_TEXT = '{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'
ODT_TABLE = '{urn:oasis:names:tc:opendocument:xmlns:table:1.0}'
MAX_TEXT = 220_000
MAX_ZIP_MEMBER = 12 * 1024 * 1024


def esc(value) -> str:
    return html.escape(str(value if value is not None else ''), quote=True)


def _valid_local_url(value: str) -> str:
    if not value.startswith('/') or value.startswith('//') or any(c in value for c in '<>"\'\r\n'):
        raise ValueError('Nieprawidłowy lokalny adres podglądu.')
    return value


def _panel(content: str, heading: str='Podgląd załączonego pliku') -> str:
    return ("<section class='card rk-file-preview' style='margin-top:14px;min-width:0'>"
            f"<h2>{esc(heading)}</h2>{content}</section>")


def _notice(message: str) -> str:
    return "<div class='small muted' style='margin:10px 0'>"+esc(message)+"</div>"


def _read_text(path: Path, limit: int=MAX_TEXT) -> str:
    with path.open('rb') as f: raw=f.read(limit+1)
    clipped=len(raw)>limit
    raw=raw[:limit]
    for enc in ('utf-8-sig','cp1250','latin1'):
        try:
            s=raw.decode(enc)
            break
        except UnicodeDecodeError: continue
    else: s=raw.decode('utf-8','replace')
    return s + ('\n\n[PODGLĄD SKRÓCONY — pozostała część w oryginale]' if clipped else '')


def _zip_xml(archive: zipfile.ZipFile, member: str):
    info=archive.getinfo(member)
    if info.file_size>MAX_ZIP_MEMBER:
        raise ValueError('Element dokumentu jest za duży dla szybkiego podglądu.')
    with archive.open(member) as f:
        data=f.read(MAX_ZIP_MEMBER+1)
    if len(data)>MAX_ZIP_MEMBER: raise ValueError('Przekroczono limit odczytu dokumentu.')
    return ET.fromstring(data)


def _word_run(node) -> str:
    parts=[]
    for ch in node.iter():
        if ch.tag==W+'t': parts.append(esc(ch.text or ''))
        elif ch.tag==W+'tab': parts.append('&emsp;')
        elif ch.tag in {W+'br',W+'cr'}: parts.append('<span style="display:block"></span>')
    value=''.join(parts)
    props=node.find(W+'rPr')
    if props is not None:
        if props.find(W+'b') is not None: value='<strong>'+value+'</strong>'
        if props.find(W+'i') is not None: value='<em>'+value+'</em>'
        if props.find(W+'u') is not None: value='<u>'+value+'</u>'
    return value


def _word_paragraph(node):
    if node.tag != W+'p': return ''
    content=''.join(_word_run(r) for r in node.findall('.//'+W+'r'))
    props=node.find(W+'pPr')
    style=props.find(W+'pStyle') if props is not None else None
    typ=style.get(W+'val','') if style is not None else ''
    if typ.lower().startswith('heading') or typ.lower().startswith('nagowek'):
        level=3 if ('2' in typ or '3' in typ) else 2
        return f'<h{level} style="margin:15px 0 7px">{content}</h{level}>'
    return '<p style="margin:5px 0;line-height:1.5;white-space:pre-wrap">'+(content or '&nbsp;')+'</p>'


def _word_table(table):
    rows=[]
    for tr in table.findall(W+'tr')[:80]:
        cells=[]
        for tc in tr.findall(W+'tc')[:20]:
            content=''.join(_word_paragraph(p) for p in tc.findall('.//'+W+'p'))
            cells.append('<td style="padding:5px;border:1px solid #ccc;vertical-align:top">'+content+'</td>')
        rows.append('<tr>'+''.join(cells)+'</tr>')
    return '<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%">'+''.join(rows)+'</table></div>'


def _docx(path):
    with zipfile.ZipFile(path) as z:
        root=_zip_xml(z,'word/document.xml')
    body=root.find('.//'+W+'body')
    if body is None: return _notice('Brak treści w pliku Word.')
    parts=[]
    for el in list(body)[:550]:
        if el.tag==W+'p': parts.append(_word_paragraph(el))
        elif el.tag==W+'tbl': parts.append(_word_table(el))
    return '<div class="rk-word-sheet" style="background:#fff;max-width:900px;padding:24px;margin:auto;overflow-wrap:anywhere;font:15px/1.5 Georgia,serif">'+''.join(parts)+'</div>'+_notice('Podgląd Worda zachowuje akapity, nagłówki i tabele; układ stron, przypisy, obrazy i odstępy mogą odbiegać od Microsoft Word.')


def _odt(path):
    with zipfile.ZipFile(path) as z: root=_zip_xml(z,'content.xml')
    blocks=[]
    for node in root.iter():
        if node.tag in {ODT_TEXT+'p',ODT_TEXT+'h'}:
            text=''.join(node.itertext()).strip()
            if text:
                tag='h3' if node.tag==ODT_TEXT+'h' else 'p'
                blocks.append(f'<{tag} style="margin:6px 0;white-space:pre-wrap">{esc(text)}</{tag}>')
            if len(blocks)>=500:break
    return '<div style="background:#fff;max-width:900px;padding:24px;margin:auto;overflow-wrap:anywhere">'+''.join(blocks)+'</div>'+_notice('Podgląd ODT może nie odtwarzać dokładnie formatowania i paginacji.')


def _ods(path):
    with zipfile.ZipFile(path) as z: root=_zip_xml(z,'content.xml')
    parts=[]
    for tab in list(root.iter(ODT_TABLE+'table'))[:4]:
        rows=[]
        for tr in list(tab.iter(ODT_TABLE+'table-row'))[:120]:
            cells=[]
            for td in [x for x in tr if x.tag in {ODT_TABLE+'table-cell',ODT_TABLE+'covered-table-cell'}][:18]:
                text=' '.join(''.join(p.itertext()) for p in td.iter(ODT_TEXT+'p'))
                repeat=min(18,int(td.attrib.get(ODT_TABLE+'number-columns-repeated','1') or 1))
                cells.extend(['<td style="padding:5px;border:1px solid #ccc">'+esc(text[:200])+'</td>']*repeat)
                if len(cells)>=18:break
            rows.append('<tr>'+''.join(cells[:18])+'</tr>')
        parts.append('<h3>'+esc(tab.attrib.get(ODT_TABLE+'name','Arkusz'))+'</h3><div style="overflow:auto;max-height:520px"><table style="border-collapse:collapse;font-size:13px">'+''.join(rows)+'</table></div>')
    return ''.join(parts)+_notice('Podgląd ODS jest ograniczony do 4 arkuszy × 120 wierszy × 18 kolumn.')


def _pptx(path):
    with zipfile.ZipFile(path) as z:
        names=sorted((x for x in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',x)),key=lambda x:int(re.search(r'\d+',x).group()))
        blocks=[]
        for i,name in enumerate(names[:60],1):
            root=_zip_xml(z,name)
            text='\n'.join(x.text or '' for x in root.iter(A+'t') if x.text)
            blocks.append(f'<div style="border:1px solid #ddd;padding:18px;margin:12px 0;background:#fff"><b>Slajd {i}</b><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{esc(text[:8000])}</pre></div>')
    return ''.join(blocks)+_notice('Podgląd prezentacji pokazuje tekst slajdów, nie pełną grafikę i układ.')


def _xlsx(path):
    from openpyxl import load_workbook
    wb=load_workbook(path,read_only=True,data_only=True)
    try:
        parts=[]
        for sheet in wb.worksheets[:4]:
            rows=[]
            for idx,line in enumerate(sheet.iter_rows(max_row=120,max_col=18,values_only=True)):
                if idx>=120:break
                cells=''.join('<td style="padding:5px;border:1px solid #ccc;white-space:pre-wrap">'+esc(str(v)[:150] if v is not None else '')+'</td>' for v in line[:18])
                rows.append('<tr>'+cells+'</tr>')
            parts.append('<h3>'+esc(sheet.title)+'</h3><div style="overflow:auto;max-height:520px"><table style="border-collapse:collapse;font-size:13px">'+''.join(rows)+'</table></div>')
        return ''.join(parts)+_notice('Podgląd pokazuje wartości komórek, maks. 4 arkusze × 120 wierszy × 18 kolumn; nie wykonuje makr ani formuł.')
    finally: wb.close()


def _rtf(path):
    data=path.read_bytes()[:MAX_TEXT]
    # Minimalny i bezpieczny podgląd RTF. Nie interpretujemy aktywnych pól.
    content=data.decode('latin1',errors='replace')
    content=re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m[1]).decode('cp1250','replace'),content)
    content=re.sub(r'\\u(-?\d+)\??',lambda m:chr(int(m[1])%65536),content)
    content=re.sub(r'\\(?:par|line)\b\s*','\n',content)
    content=re.sub(r'\\[A-Za-z]+-?\d*\s?','',content)
    content=re.sub(r'\\[^A-Za-z]','',content)
    content=content.replace('{','').replace('}','')
    return '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+esc(content)+'</pre>'+_notice('RTF jest wyświetlany jako tekst, bez pełnego formatowania.')


def _eml(path):
    from email.parser import BytesParser
    from email.policy import default
    with path.open('rb') as f: msg=BytesParser(policy=default).parse(f,headersonly=False)
    headings=''.join(f'<p><b>{esc(k)}:</b> {esc(str(msg.get(k,""))[:1000])}</p>' for k in ('From','To','Date','Subject'))
    body=msg.get_body(preferencelist=('plain',)) if msg.is_multipart() else msg
    text=''
    if body:
        try: text=body.get_content()
        except Exception: text=''
    return headings+'<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+esc(str(text)[:MAX_TEXT])+'</pre>'


def _zip_listing(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist()[:250]
    return '<ul style="max-height:550px;overflow:auto">'+''.join('<li>'+esc(name)+'</li>' for name in names)+'</ul>'+_notice('Pokazano nazwy elementów archiwum. Żaden plik nie został rozpakowany ani uruchomiony.')


def _pdf_html(path, base):
    import fitz
    with fitz.open(str(path)) as doc: pages=len(doc)
    if not pages: return _notice('Plik PDF jest pusty.')
    base=_valid_local_url(base)
    script=("<script>(function(){let page=1,scale=1;const pages="+str(pages)+",base="+json.dumps(base)+";"
            "window.rkPvNav=function(delta){page=Math.max(1,Math.min(pages,page+delta));rkPvShow()};"
            "window.rkPvZoom=function(delta){scale=Math.max(.6,Math.min(2.4,scale+delta));rkPvShow()};"
            "window.rkPvGo=function(){page=Math.max(1,Math.min(pages,parseInt(document.getElementById('rkPvInput').value)||1));rkPvShow()};"
            "function rkPvShow(){document.getElementById('rkPvInput').value=page;document.getElementById('rkPvZoom').textContent=Math.round(scale*100)+'%';"
            "document.getElementById('rkPvImage').src=base+'/'+page+'?zoom='+scale.toFixed(1)}"
            "})();</script>")
    return (f"<div class='case-control-bar' style='display:flex;gap:8px;flex-wrap:wrap;align-items:center'>"
            f"<button class='btn small' onclick='rkPvNav(-1)'>‹</button>"
            f"Strona <input id='rkPvInput' type='number' min='1' max='{pages}' value='1' style='max-width:75px'>"
            f" z {pages} <button class='btn small' onclick='rkPvGo()'>Pokaż</button>"
            f"<button class='btn small' onclick='rkPvNav(1)'>›</button>"
            "<button class='btn small' onclick='rkPvZoom(-.2)'>−</button><span id='rkPvZoom'>100%</span>"
            "<button class='btn small' onclick='rkPvZoom(.2)'>+</button></div>"
            f"<div style='overflow:auto;text-align:center;max-height:65vh;background:#e9ebef;padding:10px'>"
            f"<img id='rkPvImage' src='{esc(base)}/1?zoom=1' style='max-width:100%;height:auto;box-shadow:0 3px 12px #999' alt='Podgląd PDF'></div>"+script)


def render_preview(path: Path, filename: str, file_url: str, *, pdf_pages_base: str|None=None, image_url: str|None=None) -> str:
    """Zwraca bezpieczny panel HTML; nigdy nie zapisuje pliku ani nie zmienia bazy."""
    path=Path(path); ext=Path(filename or path.name).suffix.lower()
    url=_valid_local_url(file_url)
    if not path.is_file(): return _panel(_notice('Nie znaleziono oryginalnego pliku.'))
    size=path.stat().st_size
    info=f'<div class="small muted">{esc(filename or path.name)} · {size/1024/1024:.2f} MB</div>'
    download=f'<p><a class="btn small" href="{esc(url)}?download=1">Pobierz oryginał</a></p>'
    if size==0: return _panel(info+_notice('Plik jest pusty.')+download)
    if ext in OFFICE and size>35*1024*1024:
        return _panel(info+_notice('Plik pakietu Office przekracza 35 MB. Bezpieczny podgląd wyłączono; oryginał można pobrać.')+download)
    try:
        if ext in IMAGE_NATIVE:
            if size>50*1024*1024:
                content=_notice('Obraz jest zbyt duży do automatycznego podglądu.')
            else:
                content=f'<div style="text-align:center;overflow:auto;max-height:70vh"><img src="{esc(url)}" alt="{esc(filename)}" style="max-width:100%;height:auto"></div>'
        elif ext in {'.tif','.tiff'}:
            content=(f'<img src="{esc(_valid_local_url(image_url))}" alt="{esc(filename)}" style="max-width:100%;height:auto">' if image_url else _notice('Podgląd TIFF wymaga konwersji do PNG.'))
        elif ext in AUDIO:
            content=(f'<audio controls preload="metadata" style="width:100%"><source src="{esc(url)}">'
                     'Przeglądarka nie obsługuje odtwarzania tego formatu.</audio>'
                     +_notice('Odtwarzanie zależy od kodeków dostępnych w Windows/Qt. Nagranie pozostaje lokalne.'))
        elif ext in VIDEO:
            content=(f'<video controls preload="metadata" playsinline style="width:100%;max-height:70vh;background:#111"><source src="{esc(url)}">'
                     'Przeglądarka nie obsługuje odtwarzania tego formatu.</video>'
                     +_notice('Najlepsza zgodność: MP4 (H.264/AAC) i WebM. Inne kodeki mogą wymagać zewnętrznego odtwarzacza.'))
        elif ext=='.pdf':
            content=_pdf_html(path,pdf_pages_base) if pdf_pages_base else _notice('Brak modułu renderowania PDF.')
        elif ext=='.docx':content=_docx(path)
        elif ext=='.odt':content=_odt(path)
        elif ext=='.pptx':content=_pptx(path)
        elif ext in {'.xlsx','.xlsm','.ods'}:
            content=_ods(path) if ext=='.ods' else _xlsx(path)
        elif ext=='.rtf':content=_rtf(path)
        elif ext=='.eml':content=_eml(path)
        elif ext=='.zip':content=_zip_listing(path)
        elif ext in TEXT:
            content='<pre style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:70vh;overflow:auto">'+esc(_read_text(path))+'</pre>'
        else:
            content=_notice(f'Format {ext or "nieznany"} nie ma bezpiecznego podglądu wbudowanego. Możesz pobrać oryginał albo otworzyć go w programie systemowym.')
    except Exception as exc:
        content=_notice('Nie udało się wyświetlić podglądu: '+str(exc)[:180]+'. Oryginalny plik pozostał bez zmian.')
    return _panel(info+content+download)


def _mime_for(filename: str) -> str:
    ext=Path(filename).suffix.lower()
    return MIME.get(ext) or mimetypes.guess_type(filename)[0] or 'application/octet-stream'


def serve_local_file(handler, path: Path, filename: str, *, download: bool=False):
    """Lokalne strumieniowanie z Range dla audio/wideo; nigdy nie renderuje HTML z pliku."""
    from urllib.parse import urlparse,parse_qs
    path=Path(path)
    if not path.is_file(): return handler.send_error(404)
    download = download or (parse_qs(urlparse(getattr(handler,'path','')).query).get('download',['0'])[0]=='1')
    name=Path(filename or path.name).name
    size=path.stat().st_size
    ext=Path(name).suffix.lower()
    allowed_inline=(IMAGE_NATIVE | AUDIO | VIDEO | {'.pdf'})
    inline=ext in allowed_inline and not download
    ctype=_mime_for(name) if inline else 'application/octet-stream'
    if ctype=='application/octet-stream':inline=False
    disposition='inline' if inline else 'attachment'
    ranged=handler.headers.get('Range','') if inline else ''
    start,end=0,max(0,size-1)
    if ranged:
        match=re.fullmatch(r'bytes=(\d*)-(\d*)',ranged.strip())
        if not match or not size or (not match[1] and not match[2]):
            handler.send_response(416);handler.send_header('Content-Range',f'bytes */{size}');handler.end_headers();return
        if match[1]:
            start=int(match[1]);end=int(match[2]) if match[2] else size-1
        else:
            count=int(match[2]);start=max(0,size-count);end=size-1
        if start>=size or start>end or end<0:
            handler.send_response(416);handler.send_header('Content-Range',f'bytes */{size}');handler.end_headers();return
        end=min(end,size-1)
        # Przeglądarka może dopytać o kolejną część pliku, bez wczytywania całości.
        end=min(end,start+8*1024*1024-1)
    count=end-start+1 if size else 0
    handler.send_response(206 if ranged else 200)
    handler.send_header('Content-Type',ctype)
    handler.send_header('Content-Length',str(count))
    handler.send_header('Content-Disposition',f"{disposition}; filename*=UTF-8''{quote(name)}")
    handler.send_header('Accept-Ranges','bytes')
    if ranged:handler.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    handler.send_header('Cache-Control','private, no-store')
    handler.send_header('X-Content-Type-Options','nosniff')
    handler.send_header('Cross-Origin-Resource-Policy','same-origin')
    handler.end_headers()
    try:
        with path.open('rb') as f:
            f.seek(start)
            remaining=count
            while remaining>0:
                chunk=f.read(min(1024*1024,remaining))
                if not chunk:break
                handler.wfile.write(chunk)
                remaining-=len(chunk)
    except (BrokenPipeError,ConnectionResetError,OSError):pass


def serve_pdf_page(handler, path: Path, page_number:int):
    if not path.is_file(): return handler.send_error(404)
    try:
        import fitz
        from urllib.parse import urlparse,parse_qs
        qs=parse_qs(urlparse(handler.path).query)
        zoom=float((qs.get('zoom') or ['1'])[0]); zoom=max(.6,min(2.4,zoom))
        with fitz.open(str(path)) as pdf:
            if not (1<=page_number<=len(pdf)):return handler.send_error(404)
            page=pdf[page_number-1]
            scale=1.5*zoom
            estimate=page.rect.width*page.rect.height*scale*scale
            if estimate>10_000_000:scale*=((10_000_000/estimate)**0.5)
            pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
            raw=pix.tobytes('png')
    except Exception:return handler.send_error(422,'Nie udało się wyrenderować strony PDF.')
    handler.send_response(200)
    handler.send_header('Content-Type','image/png')
    handler.send_header('Content-Length',str(len(raw)))
    handler.send_header('X-Content-Type-Options','nosniff')
    handler.send_header('Cache-Control','private, no-store')
    handler.end_headers()
    try:handler.wfile.write(raw)
    except (BrokenPipeError,ConnectionResetError,OSError):pass


def serve_tiff_as_png(handler, path: Path):
    try:
        from PIL import Image
        with Image.open(path) as img:
            if img.width*img.height>45_000_000:raise ValueError('Zbyt duży obraz')
            img.thumbnail((3500,3500))
            out=io.BytesIO()
            img.convert('RGB').save(out,format='PNG')
            raw=out.getvalue()
    except Exception:return handler.send_error(422,'Nie udało się przekonwertować obrazu.')
    handler.send_response(200)
    handler.send_header('Content-Type','image/png')
    handler.send_header('Content-Length',str(len(raw)))
    handler.send_header('X-Content-Type-Options','nosniff')
    handler.send_header('Cache-Control','private, no-store')
    handler.end_headers()
    try:handler.wfile.write(raw)
    except (BrokenPipeError,ConnectionResetError,OSError):pass
