import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest
from radar.documents import DocumentFailure,extract_isolated
from radar.evidence_sandbox import run_worker


def test_container_requires_offline_read_only_bounded_runtime_and_cleanup(monkeypatch,tmp_path):
    monkeypatch.setattr('radar.evidence_sandbox.LINUX_HOST',True)
    monkeypatch.setattr('radar.evidence_sandbox.os.getuid',lambda:1000,raising=False)
    monkeypatch.setattr('radar.evidence_sandbox.os.getgid',lambda:1000,raising=False)
    monkeypatch.setenv('DATABASE_URL','PRIVATE_DATABASE');monkeypatch.setenv('ANTHROPIC_API_KEY','PRIVATE_KEY')
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        assert 'PRIVATE' not in str(kwargs.get('env'))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('radar.evidence_sandbox.subprocess.run',run)
    assert run_worker('fixture:one',tmp_path,'radar.document_worker',[],25,768)==''
    command=calls[0]
    for value in ('--network=none','--read-only','--cap-drop=ALL','--pids-limit=32','--cpus=1','--memory=768m','--memory-swap=768m','--pull=never'):
        assert value in command
    assert '--env-file' not in command and 'PRIVATE' not in str(command)
    assert calls[-1][:3]==['docker','rm','--force']


def test_timeout_forces_only_its_own_container_removal(monkeypatch,tmp_path):
    monkeypatch.setattr('radar.evidence_sandbox.LINUX_HOST',True)
    monkeypatch.setattr('radar.evidence_sandbox.os.getuid',lambda:1000,raising=False)
    monkeypatch.setattr('radar.evidence_sandbox.os.getgid',lambda:1000,raising=False)
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        if command[1]=='run':raise subprocess.TimeoutExpired(command,25)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('radar.evidence_sandbox.subprocess.run',run)
    with pytest.raises(DocumentFailure) as error:run_worker('fixture:one',tmp_path,'radar.document_worker',[],25,768)
    assert error.value.kind=='DOCUMENT_TIMEOUT'
    assert calls[0][calls[0].index('--name')+1]==calls[-1][-1]


@pytest.mark.skipif(not os.environ.get('RADAR_TEST_EVIDENCE_IMAGE'),reason='Explicit Linux evidence container required')
def test_actual_container_parser_and_ocr_are_offline_and_keep_draft_untrusted(monkeypatch,tmp_path):
    from PIL import Image,ImageDraw,ImageFont
    from radar.ocr import extract_ocr_isolated
    image_name=os.environ['RADAR_TEST_EVIDENCE_IMAGE']
    monkeypatch.setenv('RADAR_EVIDENCE_IMAGE',image_name)
    monkeypatch.setenv('DATABASE_URL','UNAVAILABLE_SECRET')
    kind,text=extract_isolated(b'Official parser evidence','notice.txt','text/plain')
    assert kind=='txt' and text=='Official parser evidence'
    with Image.new('RGB',(1000,180),'white') as image:
        ImageDraw.Draw(image).text((30,30),'REQUIRED ATTENDANCE 70%',font=ImageFont.load_default(size=40),fill='black')
        path=tmp_path/'scan.pdf';image.save(path,'PDF')
    result=extract_ocr_isolated(path.read_bytes(),os.environ['RADAR_TEST_OCR_MODELS'])
    assert result['review_required'] and '70%' in result['pages'][0]['text']
    with pytest.raises(DocumentFailure):extract_isolated(b'corrupt','file.pdf','application/pdf')
    # Probe the same sandbox flags with a separate process, not the source parser.
    output=run_worker(image_name,tmp_path,'radar.sandbox_probe',[],25,768)
    proof=json.loads(output)
    assert proof=={'secrets_absent':True,'network_blocked':True,'root_read_only':True,'non_root':True}
