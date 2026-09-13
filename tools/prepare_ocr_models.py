"""Explicit setup download; ingestion itself never downloads executable/models."""
import argparse
import hashlib
from pathlib import Path
import tempfile
import time
import requests
from radar.ocr import MODEL_COMMIT, MODEL_HASHES, verify_models


def prepare(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for language, expected in MODEL_HASHES.items():
        destination = folder / (language + '.traineddata')
        if (destination.is_file() and destination.stat().st_size <= 20_000_000
                and hashlib.sha256(destination.read_bytes()).hexdigest() == expected):
            continue
        url = f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/{MODEL_COMMIT}/{language}.traineddata'
        temporary = None
        try:
            started = time.monotonic()
            size = 0
            digest = hashlib.sha256()
            with requests.get(url, stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                with tempfile.NamedTemporaryFile(dir=folder, delete=False) as file:
                    temporary = Path(file.name)
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 20_000_000 or time.monotonic() - started > 90:
                            raise ValueError('OCR model download limit exceeded')
                        digest.update(chunk)
                        file.write(chunk)
            if digest.hexdigest() != expected:
                raise ValueError('OCR model download hash mismatch')
            temporary.replace(destination)
        finally:
            if temporary and temporary.exists():
                temporary.unlink(missing_ok=True)
    verify_models(folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    prepare(parser.parse_args().directory)
    print('Pinned Korean and English OCR models verified.')
