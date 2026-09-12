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

Document extractors support HTML, text-bearing PDF, HWP v5 BodyText, HWPX XML and DOCX XML. Scanned/encrypted/unsupported or corrupt files are failures, never invented evidence. File size, archive expansion, page count and extracted text are bounded. OCR is not implemented. Extraction currently runs in-process; a resource-isolated worker with CPU/memory time limits is still needed for robust hostile-document handling.
