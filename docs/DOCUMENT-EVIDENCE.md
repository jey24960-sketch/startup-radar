# Attachment evidence and review

StartupRadar downloads attachments through the source's bounded, host-approved,
robots-aware HTTP client and parses each in an isolated subprocess. A successful
download is not a successful text extraction. The original URL, filename, MIME,
hash and fetch timestamp remain available when parsing fails.

The parser recognizes PDF, HWP, HWPX, DOCX, supported HTML and UTF-8 text. PNG/JPEG
signatures identify image evidence requiring OCR/manual review; they do not prove
the image is valid or readable. No OCR engine is installed or invoked by this
change. Images retain `extraction_status=FAILED`, without invented text.

## Failure categories

| error_kind | Meaning and next action |
| --- | --- |
| DOCUMENT_OCR_REQUIRED | Image attachment, or PDF page with content/annotations but no readable text. Inspect the listed pages and obtain reviewed OCR or publisher text. |
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
