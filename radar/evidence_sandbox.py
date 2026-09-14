"""Production evidence workers: offline OCI container, one disposable input directory."""
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

LINUX_HOST=sys.platform=='linux'


def run_worker(image,folder,module,args,timeout,memory_mb):
    from radar.documents import DocumentFailure
    if not re.fullmatch(r'(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9._/-]*:[a-zA-Z0-9._-]+)',image):
        raise DocumentFailure('DOCUMENT_PROCESS','Evidence image must be an explicit image ID or tag')
    if not LINUX_HOST:raise DocumentFailure('DOCUMENT_PROCESS','Production evidence sandbox requires a Linux Docker host')
    name='radar-evidence-'+uuid4().hex
    command=['docker','run','--rm','--pull=never','--name',name,'--label','startup-radar.evidence=true',
        '--network=none','--cap-drop=ALL','--security-opt=no-new-privileges','--read-only',
        '--pids-limit=32','--cpus=1',f'--memory={memory_mb}m',f'--memory-swap={memory_mb}m',
        '--ulimit','core=0','--ulimit','fsize=4194304:4194304',
        '--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
        '--mount',f'type=bind,source={Path(folder).resolve()},target=/evidence',
        '--env','OMP_THREAD_LIMIT=1',image,'python','-m',module,*args]
    env={key:value for key,value in os.environ.items() if key in ('PATH','HOME','DOCKER_HOST','DOCKER_CONTEXT')}
    try:
        # Files cap parent memory even if a damaged native parser emits diagnostics.
        with (Path(folder)/'stdout.log').open('wb') as stdout,(Path(folder)/'stderr.log').open('wb') as stderr:
            result=subprocess.run(command,stdout=stdout,stderr=stderr,timeout=timeout,env=env)
        if any((Path(folder)/name).stat().st_size>2_000_000 for name in ('stdout.log','stderr.log')):
            raise DocumentFailure('DOCUMENT_LIMIT','Evidence sandbox diagnostic output limit')
        if result.returncode:raise DocumentFailure('DOCUMENT_PROCESS','Evidence sandbox failed or reached resource limits')
        return (Path(folder)/'stdout.log').read_text(encoding='utf-8')
    except subprocess.TimeoutExpired:
        raise DocumentFailure('DOCUMENT_TIMEOUT','Evidence sandbox time limit exceeded') from None
    except OSError:
        raise DocumentFailure('DOCUMENT_PROCESS','Evidence sandbox runtime is unavailable; no native fallback') from None
    finally:
        try:
            subprocess.run(['docker','rm','--force',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,env=env)
        except (OSError,subprocess.TimeoutExpired):
            # Surface cleanup uncertainty; an operator must check this worker label.
            raise DocumentFailure('DOCUMENT_PROCESS','Evidence container cleanup unconfirmed') from None
