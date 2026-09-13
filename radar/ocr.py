"""Optional local OCR. Output is a review draft, never trusted eligibility text."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from radar.documents import DocumentFailure

VERSION = 'ocr-review-1'
MODEL_COMMIT = 'e12c65a915945e4c28e237a9b52bc4a8f39a0cec'
MODEL_HASHES = {
    'kor': 'f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff',
    'eng': '8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba',
}
MAX_PAGES = 20
MAX_PAGE_PIXELS = 16_000_000
MAX_TOTAL_PIXELS = 80_000_000
MAX_DRAFT_TEXT = 100_000
MAX_RESULT_BYTES = 2_000_000


def verify_models(folder):
    for language, expected in MODEL_HASHES.items():
        path = Path(folder) / (language + '.traineddata')
        if not path.is_file() or path.stat().st_size > 20_000_000:
            raise DocumentFailure('DOCUMENT_OCR_SETUP', 'Pinned OCR language model missing or oversized')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise DocumentFailure('DOCUMENT_OCR_SETUP', 'OCR language model hash mismatch')


def validate_draft(result, content_hash):
    pages = result.get('pages', [])
    if (result.get('version') != VERSION or result.get('content_hash') != content_hash
            or result.get('review_required') is not True or not 1 <= len(pages) <= MAX_PAGES
            or [p.get('page') for p in pages] != list(range(1, len(pages) + 1))
            or result.get('page_count') != len(pages)
            or sum(len(p.get('text', '')) for p in pages) > MAX_DRAFT_TEXT):
        raise DocumentFailure('DOCUMENT_PROCESS', 'Invalid OCR review result')
    return result


def extract_ocr_isolated(data, model_dir, cache_dir=None, timeout=120):
    """Native OCR runs in one child process without worker credentials or downloads."""
    if len(data) > 20_000_000:
        raise DocumentFailure('DOCUMENT_LIMIT', 'OCR file size limit')
    verify_models(model_dir)
    try:
        versions = {name: importlib.metadata.version(name) for name in ('tesserocr', 'pypdfium2', 'Pillow')}
    except importlib.metadata.PackageNotFoundError:
        raise DocumentFailure('DOCUMENT_OCR_SETUP', 'Install the optional OCR requirements') from None
    content_hash = hashlib.sha256(data).hexdigest()
    identity = {'version': VERSION, 'content_hash': content_hash, 'models': MODEL_HASHES,
                'packages': versions, 'platform': sys.platform, 'python': sys.version.split()[0]}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache = Path(cache_dir) / (key + '.json') if cache_dir else None
    if cache and cache.is_file() and cache.stat().st_size <= MAX_RESULT_BYTES:
        try:
            cached = json.loads(cache.read_text(encoding='utf-8'))
            if cached['identity'] == identity:
                return validate_draft(cached['result'], content_hash)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass  # A damaged local cache never becomes authoritative evidence.
    with tempfile.TemporaryDirectory(prefix='radar-ocr-') as folder:
        path = Path(folder) / 'document.bin'
        output = Path(folder) / 'result.json'
        path.write_bytes(data)
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP')}
        env.update(PYTHONIOENCODING='utf-8', OMP_THREAD_LIMIT='1')
        try:
            process = subprocess.run([sys.executable, '-m', 'radar.ocr_worker', str(path),
                str(Path(model_dir).resolve()), str(output)], cwd=Path(__file__).resolve().parent.parent,
                env=env, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise DocumentFailure('DOCUMENT_TIMEOUT', 'OCR review time limit exceeded') from None
        if process.returncode or not output.is_file():
            raise DocumentFailure('DOCUMENT_PROCESS', 'OCR process failed or resource limit exceeded')
        if output.stat().st_size > MAX_RESULT_BYTES:
            raise DocumentFailure('DOCUMENT_LIMIT', 'OCR review output limit')
        result = json.loads(output.read_text(encoding='utf-8'))
        if result.get('error'):
            raise DocumentFailure(result.get('error_kind'), result['error'])
        result = validate_draft(result, content_hash)
    if cache:
        # Cache loss is harmless; the private DB source snapshot remains provenance.
        temporary = None
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=cache.parent, delete=False) as file:
                temporary = Path(file.name)
                json.dump({'identity': identity, 'result': result}, file, ensure_ascii=False)
            temporary.replace(cache)
        except OSError:
            pass
        finally:
            if temporary and temporary.exists():
                temporary.unlink(missing_ok=True)
    return result


def review_metadata(documents, metadata=None):
    """Persist drafts even when normalized program version/AI analysis is unchanged."""
    result = dict(metadata or {})
    drafts = [{'original_url': doc['original_url'], 'filename': doc['filename'],
               'content_hash': doc.get('content_hash'), 'draft': doc['ocr_review']}
              for doc in documents or [] if doc.get('ocr_review')]
    if drafts:
        result['document_ocr_reviews'] = sorted(drafts, key=lambda doc: doc['original_url'])
    return result
