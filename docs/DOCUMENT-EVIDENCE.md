# Attachment evidence and review

StartupRadar downloads attachments through the source's bounded, host-approved,
robots-aware HTTP client and parses each in an isolated subprocess. A successful
download is not a successful text extraction. The original URL, filename, MIME,
hash and fetch timestamp remain available when parsing fails.

The parser recognizes PDF, HWP, HWPX, DOCX, supported HTML and UTF-8 text. PNG/JPEG
signatures identify image evidence requiring OCR/manual review; they do not prove
the image is valid or readable. Optional local OCR can produce a separate review
draft. Images retain `extraction_status=FAILED`; draft text is never inserted into
the trusted `extracted_text` field or passed to requirement extraction.

## Failure categories

| error_kind | Meaning and next action |
| --- | --- |
| DOCUMENT_OCR_REQUIRED | Image attachment, or PDF page with content/annotations but no readable text. Inspect the listed pages and obtain reviewed OCR or publisher text. |
| DOCUMENT_OCR_REVIEW | Local OCR produced a draft. Compare every page and critical condition with the original; engine confidence is not approval. |
| DOCUMENT_OCR_SETUP | Optional native packages or pinned language models are missing/invalid. Complete explicit setup or leave OCR disabled. |
| DOCUMENT_EMPTY | No text was extracted and no nonempty PDF page content was detected, or a supported text document was empty. Review the original. |
| DOCUMENT_LIMIT | Parser file/page/archive/text limit exceeded. Review separately; do not raise limits blindly. |
| DOCUMENT_TIMEOUT | Isolated parser exceeded its time allowance. Investigate the document before a bounded retry. |
| DOCUMENT_PROCESS | Parser process exited unsuccessfully, possibly due to resource limits. Inspect worker diagnostics. |
| DOCUMENT_PARSE | Corrupt, encrypted, unsupported/mismatched content, or another parser error. Inspect the original; this code alone does not prove file corruption. |
| SIZE_LIMIT / other HTTP failures | Download failed before parsing. Existing fetch failure codes remain unchanged. |

All failure categories remain non-successful for eligibility. Typed failure codes
cross the subprocess boundary through a fixed allowlist and use existing database
text fields; no schema or permission migration is required. The GFC detail
projection already exposes `error_kind`; this change does not add specialized
frontend explanations.

## PDF page coverage

Each page is extracted separately. If a page contains a nonempty content stream
or annotations but yields no readable text, the entire file stays failed, with
one-based page numbers in the diagnostic. Partial text is not promoted as complete
evidence. Truly blank pages without content/annotations do not invalidate readable
pages. Text limits are checked incrementally before moving to subsequent pages.

This is a conservative missing-page check, not OCR or a guarantee of semantic
completeness. A page with a small text header and a scanned body can still yield
some text; an OCR layer can itself be wrong. Decorative graphic-only pages may be
sent to manual review. Tables, reading order, drawn glyphs, nested document content
and the accuracy of HWP extraction still need separate validation. Do not ignore
an unread attachment merely because its name says poster or because another
attachment is readable.

The eligibility extractor still requires every attachment to succeed as well as
grounded, supported requirements. A model's `evidence_complete=true` cannot
override an unread page. Independently verified disqualifying conditions continue
to apply. Parser changes take effect on the next acquisition; historical document
records and existing recommendations are not automatically rewritten. A changed
document extraction status/text participates in the existing analysis cache key.

## Actual evidence inspected on 2026-09-13

The prior 19-program catalog audit contained 15 failed attachments: 12 image
posters, one image-only PDF, one PDF parse error and one download size limit.
Three representative original downloads were retrieved again without calling AI,
saving to the shared database or sending notifications:

- [Pre-WoW six-page card news](https://www.k-startup.go.kr/afile/fileDownload/D7XLn): all six pages contain images but no extractable text. Visual inspection confirms offline attendance and a 70% completion requirement. Its first page says applications start September 7, while the previously inspected portal period starts September 9; do not silently reconcile this discrepancy.
- [Pre-WoW poster](https://www.k-startup.go.kr/afile/fileDownload/ksXLn): PNG signature; OCR/manual review required.
- [SVC Seoul internship announcement](https://www.k-startup.go.kr/afile/fileDownload/xwXLn): PDF signature, 69,632 bytes; pypdf reports an unexpectedly ended stream. No automatic repair or successful extraction is claimed.

These are parser observations, not evidence that a member is eligible. Useful
current recommendations still require reviewed image content and explicit models
for attendance, future commitments and other unsupported conditions.

Reference: [pypdf text extraction limitations](https://pypdf.readthedocs.io/en/6.18.1/user/extract-text.html).

## Optional local OCR review

Install `requirements-v2.lock.txt` followed by `requirements-ocr.lock.txt`. The
optional lock supports Windows x64 CPython 3.11/3.12 and the Linux CI runtime.
Windows wheels come from the builder linked by the
[tesserocr project](https://github.com/sirfz/tesserocr), with their SHA-256 pinned.
No system-wide executable is installed. Linux uses the pinned PyPI wheel.

Prepare the official Korean/English `tessdata_best` files once:

```sh
python -m tools.prepare_ocr_models work/tessdata
python -m tools.ocr_review downloaded-original.pdf --models work/tessdata --cache work/ocr-cache --output review.json
```

The setup command downloads only two fixed URLs at commit
`e12c65a915945e4c28e237a9b52bc4a8f39a0cec`, checks size/time limits and SHA-256,
and atomically replaces each completed model. Ingestion never downloads models.
Model files are checked again before use. Models/cache/originals belong outside
Git and published artifacts unless an original is deliberately included for review.

For acquisition fallback, set `RADAR_OCR_MODEL_DIR` to the prepared directory and
optionally `RADAR_OCR_CACHE_DIR` to a persistent local cache. Empty/unset model
configuration preserves the existing OCR-required failure. Fallback only runs
after `DOCUMENT_OCR_REQUIRED`, not for corrupt PDFs or download failures.
CI tests this optional path; production Docker and scheduled workers do not
implicitly install or enable it. No schedule or deployment setting is changed.

The worker renders every PDF page at scale 3 and uses Korean+English LSTM sparse
text segmentation. A draft records the original content hash, engine version,
model hashes, page count, page text, image dimensions and text-line boxes with
confidence values. Coordinates refer to the rendered image in pixels. Confidence
does not measure completeness or correctness; a high-scoring page may omit a
mandatory condition. The real six-page Pre-WoW pilot demonstrated that failure.

Limits are 20 MB input, 20 pages, 16 million pixels per page, 80 million total
pixels, 100,000 draft text characters and 2 MB result JSON. There is a 120-second
wall timeout; Linux additionally limits CPU to 100 seconds and address space to
1.5 GiB. Windows has the wall/page/pixel limits but no equivalent address-space
cap. OCR executes within one child process, with a restricted environment that
excludes database/API/Telegram credentials. A late-page failure or limit returns
no partial draft. This is process/resource isolation, not an OS network sandbox.

When configured, the local cache is keyed by document bytes, OCR protocol/model
hashes, package versions, platform and Python version. A damaged cache is ignored;
cache writes are atomic and expendable. There is no automatic eviction: operators
must bound cache disk usage or rotate this expendable directory. Cross-run reuse
requires a persistent directory; no GitHub Actions production cache is enabled.

During `save_program`, OCR drafts are stored in the existing private
`program_source_snapshots.extraction_metadata.document_ocr_reviews` alongside URL,
filename and hash. This also runs when the normalized program version is unchanged;
identical observations deduplicate. Historical `documents` rows are not rewritten.
No schema, grant or RLS change is needed. The member-facing source-review RPC does
not project these raw snapshots. This checkpoint supplies an operator JSON review
artifact, not a GFC review/approval screen.

Because unreviewed draft text does not participate in the requirement extractor's
input, unchanged evidence does not trigger another AI call merely because an OCR
draft appeared. The document remains failed, keeping incomplete programs
`UNVERIFIABLE`. No automatic or manual approval action is implemented here. A
future approval path must bind a reviewer decision to exact file/page evidence and
model mandatory attendance, fixed dates, alternatives and commitments explicitly.
