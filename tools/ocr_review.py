"""Create a local OCR review JSON for a downloaded original; does not approve it."""
import argparse
import json
from pathlib import Path
from radar.ocr import extract_ocr_isolated


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('document')
    parser.add_argument('--models', required=True)
    parser.add_argument('--cache')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    path = Path(args.document)
    if path.stat().st_size > 20_000_000:
        parser.error('Document exceeds the 20 MB OCR input limit')
    draft = extract_ocr_isolated(path.read_bytes(), args.models, args.cache)
    Path(args.output).write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Saved {draft['page_count']} pages for source comparison. Review is required.")
