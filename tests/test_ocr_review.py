import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest
from radar.documents import DocumentFailure, fetch_document
from radar.ocr import VERSION, extract_ocr_isolated, verify_models


def draft(data=b'fixture'):
    return {'version': VERSION, 'content_hash': hashlib.sha256(data).hexdigest(),
            'review_required': True, 'page_count': 1,
            'pages': [{'page': 1, 'text': '현장 교육 필수 참여', 'confidence': 99}]}


@pytest.fixture
def fake_runtime(monkeypatch):
    monkeypatch.setattr('radar.ocr.verify_models', lambda _: None)
    monkeypatch.setattr('radar.ocr.importlib.metadata.version', lambda _: 'fixture')


def test_ocr_draft_never_becomes_successful_document_or_model_evidence(monkeypatch):
    from radar.adapters.base import AcquiredDetail
    from radar.extraction import RequirementExtractor
    from radar.models import Program, TeamProfile
    from radar.eligibility import evaluate
    monkeypatch.setenv('RADAR_OCR_MODEL_DIR', 'fixture')
    monkeypatch.setattr('radar.documents.extract_isolated', lambda *_: (_ for _ in ()).throw(
        DocumentFailure('DOCUMENT_OCR_REQUIRED', 'scan')))
    monkeypatch.setattr('radar.ocr.extract_ocr_isolated', lambda *_: draft())
    http = SimpleNamespace(get=lambda url: (b'fixture', 'image/png', url))
    doc = fetch_document(http, 'https://example.org/poster', 'poster.png')
    assert doc['extraction_status'] == 'FAILED' and doc['error_kind'] == 'DOCUMENT_OCR_REVIEW'
    assert 'extracted_text' not in doc and doc['ocr_review']['review_required']
    text = '누구나 신청 가능합니다.'
    def respond(**kwargs):
        assert '현장 교육 필수 참여' not in json.dumps(kwargs, ensure_ascii=False)
        payload = {'requirements': [], 'program_types': ['EDUCATION'],
                   'eligibility_section_quote': text, 'evidence_complete': True}
        return SimpleNamespace(content=[SimpleNamespace(type='text', text=json.dumps(payload))])
    client = SimpleNamespace(messages=SimpleNamespace(create=respond))
    program = Program(title='Fixture', organization='Fixture', official_url='https://example.org/notice')
    result = RequirementExtractor(client).extract(program, AcquiredDetail(program.official_url, text, program.title), [doc], 'source')
    assert evaluate(TeamProfile(), result.requirements, result.evidence_complete).status == 'UNVERIFIABLE'


def test_ocr_not_invoked_without_explicit_configuration(monkeypatch):
    monkeypatch.delenv('RADAR_OCR_MODEL_DIR', raising=False)
    monkeypatch.setattr('radar.ocr.extract_ocr_isolated', lambda *_: pytest.fail('OCR was not enabled'))
    doc = fetch_document(SimpleNamespace(get=lambda url: (b'\x89PNG\r\n\x1a\n', 'image/png', url)),
                         'https://example.org/poster', 'poster.png')
    assert doc['error_kind'] == 'DOCUMENT_OCR_REQUIRED'


def test_cache_reuses_draft_but_invalidates_for_new_bytes_and_ignores_corruption(fake_runtime, monkeypatch, tmp_path):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        Path(command[-1]).write_text(json.dumps(draft(Path(command[3]).read_bytes())), encoding='utf-8')
        assert 'DATABASE_URL' not in kwargs['env'] and 'ANTHROPIC_API_KEY' not in kwargs['env']
        assert kwargs['env']['OMP_THREAD_LIMIT'] == '1'
        return SimpleNamespace(returncode=0)
    monkeypatch.setenv('DATABASE_URL', 'fixture-secret')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fixture-secret')
    monkeypatch.setattr('radar.ocr.subprocess.run', run)
    first = extract_ocr_isolated(b'fixture', tmp_path, tmp_path / 'cache')
    assert extract_ocr_isolated(b'fixture', tmp_path, tmp_path / 'cache') == first and len(calls) == 1
    extract_ocr_isolated(b'changed', tmp_path, tmp_path / 'cache')
    assert len(calls) == 2
    for path in (tmp_path / 'cache').glob('*.json'):
        path.write_text('invalid json', encoding='utf-8')
    extract_ocr_isolated(b'fixture', tmp_path, tmp_path / 'cache')
    assert len(calls) == 3


@pytest.mark.parametrize('mode,kind', [('timeout', 'DOCUMENT_TIMEOUT'), ('crash', 'DOCUMENT_PROCESS'),
                                     ('partial', 'DOCUMENT_PROCESS'), ('limit', 'DOCUMENT_LIMIT')])
def test_ocr_worker_failures_never_return_partial_success(mode, kind, fake_runtime, monkeypatch, tmp_path):
    def run(command, **kwargs):
        if mode == 'timeout':
            raise subprocess.TimeoutExpired(command, 120)
        if mode == 'crash':
            return SimpleNamespace(returncode=1)
        result = draft()
        if mode == 'partial':
            result['page_count'] = 2
        else:
            result = {'error': 'pixel limit', 'error_kind': 'DOCUMENT_LIMIT'}
        Path(command[-1]).write_text(json.dumps(result), encoding='utf-8')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('radar.ocr.subprocess.run', run)
    with pytest.raises(DocumentFailure) as error:
        extract_ocr_isolated(b'fixture', tmp_path)
    assert error.value.kind == kind


def test_model_hash_mismatch_refuses_native_execution(tmp_path):
    (tmp_path / 'kor.traineddata').write_bytes(b'wrong model')
    with pytest.raises(DocumentFailure) as error:
        verify_models(tmp_path)
    assert error.value.kind == 'DOCUMENT_OCR_SETUP'


@pytest.mark.skipif(not os.environ.get('RADAR_TEST_OCR_MODELS'), reason='Optional native OCR runtime required')
def test_native_ocr_image_and_scanned_pdf_return_page_locations(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (1000, 180), 'white')
    ImageDraw.Draw(image).text((30, 30), 'REQUIRED ATTENDANCE 70%', font=ImageFont.load_default(size=40), fill='black')
    for extension, format in [('png', 'PNG'), ('pdf', 'PDF')]:
        path = tmp_path / ('evidence.' + extension)
        image.save(path, format)
        result = extract_ocr_isolated(path.read_bytes(), os.environ['RADAR_TEST_OCR_MODELS'])
        assert result['review_required'] and result['page_count'] == 1
        assert '70%' in result['pages'][0]['text'] and result['pages'][0]['lines'][0]['box']
    image.close()


@pytest.mark.skipif(not os.environ.get('RADAR_TEST_OCR_MODELS'), reason='Optional native OCR runtime required')
@pytest.mark.parametrize('width,pages,kind', [(100, 21, 'DOCUMENT_LIMIT'), (10000, 1, 'DOCUMENT_LIMIT'),
                                          (100, 1, 'DOCUMENT_EMPTY')])
def test_native_pdf_limits_and_empty_output(width, pages, kind):
    import io
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=width)
    stream = io.BytesIO()
    writer.write(stream)
    with pytest.raises(DocumentFailure) as error:
        extract_ocr_isolated(stream.getvalue(), os.environ['RADAR_TEST_OCR_MODELS'])
    assert error.value.kind == kind


@pytest.mark.skipif(not os.environ.get('RADAR_TEST_OCR_MODELS'), reason='Optional native OCR runtime required')
def test_native_image_bomb_is_rejected_before_pixel_allocation():
    import io
    import struct
    import zlib
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (1, 1)).save(buffer, 'PNG')
    data = bytearray(buffer.getvalue())
    data[16:24] = struct.pack('>II', 50000, 50000)
    data[29:33] = struct.pack('>I', zlib.crc32(data[12:29]))
    with pytest.raises(DocumentFailure) as error:
        extract_ocr_isolated(bytes(data), os.environ['RADAR_TEST_OCR_MODELS'])
    assert error.value.kind == 'DOCUMENT_LIMIT'
