"""Wydzielony odczyt tekstu z dokumentów; zależności OCR przekazywane jawnie."""
from __future__ import annotations
import io
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

def extract_document_text(filename: str, data: bytes, force_ocr: bool=False, *, find_tesseract, ocr_language_for, run_tesseract) -> tuple[str,int,str,str]:
    """Zwraca: tekst, ocr_used(0/1), ocr_status, ocr_language.

    OCR uruchamia się automatycznie tylko dla skanów/obrazów bez sensownej warstwy tekstowej.
    Nie OCR-ujemy DOCX z poprawnym tekstem.
    """
    ext=Path(filename or '').suffix.lower()
    tcmd=find_tesseract(); lang=ocr_language_for(tcmd) if tcmd else ''
    min_text=max(10,int(os.getenv('RK_OCR_MIN_TEXT','40') or 40))
    max_pages=max(1,int(os.getenv('RK_OCR_MAX_PAGES','300') or 300))
    dpi=max(120,min(350,int(os.getenv('RK_OCR_DPI','200') or 200)))
    try:
        if ext=='.docx':
            with zipfile.ZipFile(io.BytesIO(data),'r') as z:
                xml=z.read('word/document.xml')
            root=ET.fromstring(xml); texts=[]
            for el in root.iter():
                if el.tag.endswith('}t') and el.text: texts.append(el.text)
                elif el.tag.endswith('}tab'): texts.append('\t')
                elif el.tag.endswith('}br'): texts.append('\n')
            return (' '.join(texts),0,'tekst','')
        if ext=='.pdf':
            page_text=[]
            try:
                from pypdf import PdfReader
            except Exception:
                try: from PyPDF2 import PdfReader
                except Exception: PdfReader=None
            reader=PdfReader(io.BytesIO(data)) if PdfReader else None
            if reader:
                for page in reader.pages[:max_pages]:
                    try: page_text.append(page.extract_text() or '')
                    except Exception: page_text.append('')
            combined='\n'.join(page_text)
            needs_ocr=force_ocr or not combined.strip() or sum(len(x.strip()) for x in page_text)<min_text*max(1,len(page_text))
            if not needs_ocr:
                return (combined,0,'tekst','')
            if not tcmd:
                return (combined,0,'ocr_brak_silnika','')
            try:
                import fitz
            except Exception:
                return (combined,0,'ocr_brak_pymupdf',lang)
            doc=fitz.open(stream=data,filetype='pdf'); out=[]; used=False
            total=min(len(doc),max_pages)
            for i in range(total):
                existing=page_text[i] if i<len(page_text) else ''
                if not force_ocr and len(existing.strip())>=min_text:
                    out.append(existing); continue
                page=doc.load_page(i)
                pix=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)
                with tempfile.NamedTemporaryFile(suffix='.png',delete=False) as tf: img=Path(tf.name)
                try:
                    pix.save(str(img)); ocr=run_tesseract(tcmd,img,lang); out.append(ocr or existing); used=used or bool(ocr.strip())
                finally:
                    try: img.unlink()
                    except OSError: pass
            if len(doc)>max_pages: out.append(f'\n[OCR ograniczony do pierwszych {max_pages} stron]')
            return ('\n'.join(out),1 if used else 0,'ocr_ok' if used else 'ocr_brak_tekstu',lang)
        if ext in {'.png','.jpg','.jpeg','.tif','.tiff','.bmp','.webp'}:
            if not tcmd: return ('',0,'ocr_brak_silnika','')
            with tempfile.NamedTemporaryFile(suffix=ext or '.png',delete=False) as tf:
                tf.write(data); img=Path(tf.name)
            try: text=run_tesseract(tcmd,img,lang)
            finally:
                try: img.unlink()
                except OSError: pass
            return (text,1 if text.strip() else 0,'ocr_ok' if text.strip() else 'ocr_brak_tekstu',lang)
        if ext in {'.xlsx','.xlsm'}:
            try:
                import openpyxl
                wb=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=True)
                parts=[]
                for ws in wb.worksheets[:12]:
                    parts.append(f'### Arkusz: {ws.title}')
                    for n,row in enumerate(ws.iter_rows(values_only=True),1):
                        vals=['' if v is None else str(v) for v in row[:40]]
                        if any(v.strip() for v in vals): parts.append('\t'.join(vals))
                        if n>=500: parts.append('[podgląd ograniczony do 500 wierszy arkusza]'); break
                wb.close(); return ('\n'.join(parts),0,'tekst','')
            except Exception:
                return ('',0,'blad_podgladu_xlsx','')
        if ext in {'.txt','.md','.csv','.log','.rtf'}:
            for enc in ('utf-8','cp1250','latin-1'):
                try: return (data.decode(enc),0,'tekst','')
                except Exception: pass
    except Exception:
        return ('',0,'blad_indeksowania',lang)
    return ('',0,'nieobslugiwany_format','')
