"""Bounded native OCR worker. No partial file is returned after a limit/failure."""
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import warnings
from contextlib import ExitStack


def extract(data, model_dir):
    from radar.documents import DocumentFailure
    from radar.ocr import (VERSION, MODEL_HASHES, MAX_PAGES, MAX_PAGE_PIXELS,
                           MAX_TOTAL_PIXELS, MAX_DRAFT_TEXT, verify_models)
    try:
        from PIL import Image
        import pypdfium2 as pdfium
        import tesserocr
    except ImportError:
        raise DocumentFailure('DOCUMENT_OCR_SETUP', 'OCR native dependency unavailable') from None
    verify_models(model_dir)
    Image.MAX_IMAGE_PIXELS = MAX_PAGE_PIXELS
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    pages = []
    total_pixels = total_text = 0

    def recognize(image, number, api):
        nonlocal total_pixels, total_text
        width, height = image.size
        total_pixels += width * height
        if width * height > MAX_PAGE_PIXELS or total_pixels > MAX_TOTAL_PIXELS:
            raise DocumentFailure('DOCUMENT_LIMIT', 'OCR pixel limit; no partial draft accepted')
        # Composite transparent source pixels on white instead of silently black.
        rgba = image.convert('RGBA')
        canvas = Image.new('RGB', image.size, 'white')
        try:
            canvas.paste(rgba, mask=rgba.getchannel('A'))
            api.SetImage(canvas)
            text = api.GetUTF8Text()
            total_text += len(text)
            if total_text > MAX_DRAFT_TEXT:
                raise DocumentFailure('DOCUMENT_LIMIT', 'OCR draft text limit')
            lines = []
            if text.strip():
                iterator = api.GetIterator()
                while iterator:
                    try:
                        line = iterator.GetUTF8Text(tesserocr.RIL.TEXTLINE)
                    except RuntimeError:
                        line = ''  # Tesseract also visits non-text blocks.
                    if line and line.strip():
                        lines.append({'text': line.strip(), 'box': iterator.BoundingBox(tesserocr.RIL.TEXTLINE),
                                      'confidence': round(iterator.Confidence(tesserocr.RIL.TEXTLINE), 2)})
                    if len(lines) > 5000:
                        raise DocumentFailure('DOCUMENT_LIMIT', 'OCR line limit')
                    if not iterator.Next(tesserocr.RIL.TEXTLINE):
                        break
            pages.append({'page': number, 'width': width, 'height': height,
                          'text': text, 'confidence': api.MeanTextConf(), 'lines': lines})
        finally:
            rgba.close()
            canvas.close()
            api.Clear()

    with tesserocr.PyTessBaseAPI(path=str(model_dir), lang='kor+eng',
            oem=tesserocr.OEM.LSTM_ONLY, psm=tesserocr.PSM.SPARSE_TEXT) as api:
        if data.startswith(b'%PDF-'):
            with pdfium.PdfDocument(data) as document:
                if not 1 <= len(document) <= MAX_PAGES:
                    raise DocumentFailure('DOCUMENT_LIMIT', 'OCR PDF page limit')
                for index in range(len(document)):
                    with ExitStack() as cleanup:
                        page = document[index]
                        cleanup.callback(page.close)
                        width, height = page.get_size()
                        pixels = math.ceil(width * 3) * math.ceil(height * 3)
                        if pixels > MAX_PAGE_PIXELS or total_pixels + pixels > MAX_TOTAL_PIXELS:
                            raise DocumentFailure('DOCUMENT_LIMIT', 'OCR PDF render pixel limit')
                        bitmap = page.render(scale=3)
                        cleanup.callback(bitmap.close)
                        with bitmap.to_pil() as image:
                            recognize(image, index + 1, api)
        elif data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff'):
            try:
                image = Image.open(io.BytesIO(data))
            except (Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise DocumentFailure('DOCUMENT_LIMIT', 'OCR image pixel limit') from None
            with image:
                if getattr(image, 'n_frames', 1) != 1:
                    raise DocumentFailure('DOCUMENT_LIMIT', 'Animated/multiframe OCR requires separate review')
                recognize(image, 1, api)
        else:
            raise DocumentFailure('DOCUMENT_PARSE', 'OCR supports PDF and PNG/JPEG only')
    if not any(page['text'].strip() for page in pages):
        raise DocumentFailure('DOCUMENT_EMPTY', 'OCR found no readable text')
    return {'version': VERSION, 'content_hash': hashlib.sha256(data).hexdigest(),
            'review_required': True, 'engine': tesserocr.tesseract_version(),
            'languages': MODEL_HASHES, 'segmentation': 'SPARSE_TEXT', 'pdf_scale': 3,
            'coordinate_system': 'rendered image pixels: left, top, right, bottom',
            'page_count': len(pages), 'pages': pages}


def main():
    path, model_dir, output = sys.argv[1:4]
    try:
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (100, 100))
        if Path(path).stat().st_size > 20_000_000:
            from radar.documents import DocumentFailure
            raise DocumentFailure('DOCUMENT_LIMIT', 'OCR file size limit')
        result = extract(Path(path).read_bytes(), model_dir)
    except Exception as error:
        result = {'error': str(error)[:300], 'error_kind': getattr(error, 'kind', 'DOCUMENT_PARSE')}
    Path(output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
