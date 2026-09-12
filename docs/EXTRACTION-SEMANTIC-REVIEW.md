# Extraction meaning review — requirements 2.0.5

The live Seokyeong incubation notice (K-Startup publisher ID 179220) exposed three interpretation failures in requirements 2.0.4. A verbatim quote did not prove that its meaning matched the flat profile rule.

- A limit for businesses under seven years was applied as one unconditional business_age_months rule, although pre-business applicants were a separate permitted branch. The document also measured age on the announcement date, while the current evaluator measures age on its evaluation date.
- Tax arrears, credit restrictions, environmentally disruptive business activities and prohibited industries were stored as arbitrary prior_support_restrictions strings. An empty list or differently worded user input could incorrectly look like absence of all these restrictions.
- The current profile cannot confirm a promise to register a business or relocate after admission. Such obligations are not established by selecting a present business status.

Requirements 2.0.5 now withdraws certainty for AI-generated free-text history conditions and age quotes with a pre-business branch or fixed announcement-date basis. It also checks supplied source lines for explicit post-admission registration/relocation commitments, even if the model omitted them from its eligibility excerpt. These findings prevent evidence_complete from becoming true and are retained as review_flags in extraction/cache/source-snapshot metadata. This review never creates a new eligibility restriction or fills a user field.

The model prompt explicitly describes these unsupported meanings. The ordinary deterministic eligibility engine continues to let independently verified mandatory failures take precedence. UNKNOWN conditions do not become a known failure or a successful qualification merely because the AI returned valid JSON.

Verified document hashes accidentally placed in source_id are normalized to document_id with the actual source ID. The original quote/hash is retained, allowing persisted requirements to reference the document from the same program version. A source text that does not support the quote remains unverified.

Changing the extractor version invalidates obsolete cached extraction; repeated unchanged evidence with the same new version still reuses the analysis, including its review flags. Historical versions and delivered notification receipts are preserved. A previously sent NEEDS_INFO summary describes its historical assessment, not a guarantee that the current version is eligible or recommendable.

These are targeted conservative checks, not complete Korean-language condition interpretation. They may withdraw confidence in cases a human could resolve. They do not yet model arbitrary OR branches, fixed rule reference dates, future commitments, controlled tax/credit declarations or every administrative exception. Typed representations and user-facing questions for those conditions require further work. Other old catalog versions do not become semantically verified without reanalysis.
