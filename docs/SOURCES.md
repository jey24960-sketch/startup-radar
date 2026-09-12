# V2 source contracts and adding a source

Official contracts inspected 2026-09-12:

- K-Startup: https://www.data.go.kr/data/15125364/openapi.do . The page embeds Swagger; the extracted reference is kstartup-openapi.json. Host and operation: https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01 . Parameters: serviceKey, page, perPage, returnType. Response contract data.data, currentCount, matchCount/totalCount; some response envelopes expose data directly as a list. Identity pbanc_sn; notice title biz_pbanc_nm; notice URL biz_aply_url; application URL detl_pg_url. Do not swap the two merely based on English-looking names: the official field descriptions distinguish them.
- BizInfo: https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi . GET https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do . Parameters crtfcKey, dataType=json, pageUnit, pageIndex, searchCnt. Response jsonArray.item; documented notice fields seq/pblancId, title/pblancNm, link/pblancUrl, author/jrsdInsttNm, reqstDt/reqstBeginEndDe, flpthNm/fileNm and printFlpthNm/printFileNm.

Exact missing credential names: KSTARTUP_API_KEY (approved public-data service key) and BIZINFO_API_KEY (issued by BizInfo). Adapters report MISSING_CREDENTIAL, never pretend an empty API response. No real credential has been used in tests.

## Adding a Source

1. Verify the organization's public official list/feed/API and its robots/access rules. Do not guess selectors or endpoints.
2. Choose KSTARTUP, BIZINFO, RSS, HTML, BROWSER or SEARCH. API keys are referenced by environment-variable name, never stored in source config.
3. Insert a sources record through the privileged setup interface with a stable slug, name, adapter and config. Typical HTML config: url, allowed_hosts, organization, link_selector, optional detail_selector. Store only verified selectors. Each attachment/redirect host must be explicitly allowed.
4. For RSS, provide feed url and allowed_hosts. GUID/Atom ID and original notice URL remain provenance. Feed/list URL remains raw metadata.
5. Browser sources additionally require installed Playwright Chromium and optionally a verified ready_selector. They use normal public rendering, reject challenges and obey robots. Search requires an explicitly injected provider implementing name and search(query) returning title/url records. No provider means NOT_CONFIGURED; consumer search engines are never scraped.
6. A new strategy implements SourceAdapter.discover, fetch_detail, fetch_documents and normalize. Register its type in the factory. A new organization using an existing strategy only needs configuration, not core ingestion edits.
7. Add captured, labeled test fixtures and test valid empty response, failure, pagination, canonical URL, attachments and malformed fields. A fixture is not evidence of current live source health.
8. Run manually, inspect source_run_results, parsing failures and normalized evidence. Only enable scheduling after live public-source validation.

Limits: current HTML discovery requires an explicit link selector and visits one configured listing page. Additional pagination needs source-specific configuration/implementation. Official API pagination is implemented with explicit partial failure at the page limit. Existing V1 supplemental URLs have not yet all been converted and live-validated. Search injection exists; deployment configuration and a concrete provider remain pending.

Document extractors support HTML, text-bearing PDF, HWP v5 BodyText, HWPX XML and DOCX XML. Scanned/encrypted/unsupported or corrupt files are failures, never invented evidence. File size, archive expansion, page count and extracted text are bounded. OCR is not implemented. Fetched documents now run in an isolated subprocess: 25-second wall limit, plus Linux CPU/address-space limits. Windows currently has no hard subprocess memory ceiling. OCR and real-corpus validation remain pending.


## Registry and verified long-tail example

`sources.json` is the initial registry. Apply intentionally with `python -m radar.cli seed-sources`; this updates registered configuration and enabled states. Use `python -m radar.cli run --kind INGEST --source SLUG` for a single source. Keys remain in process secrets. Missing K-Startup/BizInfo credentials are visible MISSING_CREDENTIAL failures.

Live check on 2026-09-12: `https://startup.korea.ac.kr/rss` returned only institution/about pages. The RSS entry is therefore disabled. The homepage's observed `a[href*="kboard_content_redirect="]` links yielded 13 notices. The first detail's `.kboard-document-wrap` held 547 characters; explicit `button.kboard-button-download` controls exposed two public HWP downloads. Both were fetched and isolated text extraction succeeded (3,595 and 1,924 characters). Exact metadata is in `LIVE-SOURCE-CHECK.json`. HTML buttons are accepted only for the configured document selector and a literal window.location.href string; no JavaScript is evaluated.

This example represents Korea University **Sejong** Startup Education Center, not every Korea University startup organization. The homepage feed is incomplete for historical archives. Discovery success does not imply all 13 entries are currently relevant or open. The sample did not call AI, certify eligibility or send Telegram messages.
# Supplemental source audit — 2026-09-12

`LONGTAIL-SOURCE-AUDIT.json` records read-only checks of 11 legacy supplemental sources. This is an inventory audit, not a claim that all configured sources successfully ingest. The registry now contains 16 entries: four enabled (K-Startup, BizInfo, Korea Sejong HTML, KHU HTML) and twelve disabled with explicit reasons, including unconfigured search and obsolete RSS.

KHU's public homepage exposes literal `viewNotice(bbsId, boardId, menuNo)` links. Its actual script builds `/startup_kor/user/bbs/{bbsId}/view.do` with `boardId` and `menuNo` form values; a GET to the same observed route was verified. Configuration supplies a full-match regular expression with named groups and a URL template. The adapter percent-encodes captured values and never executes JavaScript. Twelve candidates were found; the first two details parsed at 665 and 507 characters. The detail title selector avoids using a listing's appended preview/date as the canonical title. Homepage discovery is not exhaustive pagination; survey/maintenance entries still need category filtering.

Hanyang's public browser DOM includes real notices, but detail HTTP is a JS shell and its PDF is behind a download button. Production resource allowlists/download mapping remain unverified, so the source is registered disabled. SBA, Dongduk, Sparklabs, Mashup, Asan and Kakao have recorded robots/host failures; no bypass was attempted. Sookmyung's old domain is a graduate department and Futureplay's observed notices are corporate governance. Primer's observed Apply page combines future rounds and says no ongoing program; stable per-program acquisition remains pending. These sources stay visible in configuration with their reason instead of being called successful empty feeds.

HTML configuration also supports `detail_title_selector` and `list_title_selector`. Duplicate image/text anchors preserve the nonempty title. Actual Unicode replacement characters in a detail produce a typed `DETAIL_ENCODING` failure instead of entering eligibility extraction. All navigation and attachment requests still go through source-specific HTTPS/host/robots checks.
