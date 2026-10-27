-- Approved 2026-10-27: source discovery expansion; no publication or send.
-- Generated from weekly-direct-sources.json by tools/export_coverage_sources_sql.py.
do $coverage$
declare proposed jsonb; previous jsonb; api record;
begin
  for proposed in select value from jsonb_array_elements($sources$[
  {
    "slug": "weekly-naver-d2sf",
    "name": "NAVER D2SF 공식 공개 모집",
    "adapter": "HTML",
    "enabled": true,
    "config": {
      "method": "BOARD",
      "url": "https://d2startup.com/ko/apply",
      "link_selector": "a[href*=\"/ko/story/\"]",
      "title_selector": ".detail_tit",
      "detail_selector": ".detail_content_area",
      "published_at_selector": ".date_info",
      "deadline_pattern": "서류\\s*접수\\s*\\(\\s*~(?P<date>\\d{1,2}월\\s*\\d{1,2}일)\\)",
      "application_link_selector": "a[href*=\"m.site.naver.com/\"]",
      "require_detail_title": true,
      "max_pages": 1,
      "max_records": 20,
      "single_page_scope": true,
      "organization": "NAVER D2SF",
      "organization_type": "CVC",
      "allowed_hosts": [
        "d2startup.com",
        "d2sf.naver.com"
      ],
      "policy_status": "APPROVED",
      "weekly_direct": true,
      "validated_at": "2026-10-27"
    }
  },
  {
    "slug": "weekly-unist-venture-notices",
    "name": "UNIST 벤처파운드리 공식 모집 공지",
    "adapter": "HTML",
    "enabled": true,
    "config": {
      "method": "BOARD",
      "url": "https://industry.unist.ac.kr/industry/community/notice01.do",
      "link_selector": ".b-title-box a[href*=\"mode=view\"]",
      "title_selector": ".b-title-box",
      "detail_selector": ".b-content-box",
      "published_at_selector": ".b-date-box",
      "require_detail_title": true,
      "pagination_link_selector": "a[href*=\"article.offset=\"]",
      "pagination_query_key": "article.offset",
      "pagination_first": 0,
      "pagination_step": 10,
      "max_pages": 5,
      "max_records": 50,
      "single_page_scope": false,
      "identity_query_keys": [
        "mode",
        "articleNo"
      ],
      "organization": "UNIST 벤처파운드리",
      "organization_type": "UNIVERSITY",
      "allowed_hosts": [
        "industry.unist.ac.kr"
      ],
      "policy_status": "APPROVED",
      "weekly_direct": true,
      "validated_at": "2026-10-27"
    }
  },
  {
    "slug": "weekly-korea-anam-programs",
    "name": "고려대 크림슨창업지원단 공개 프로그램",
    "adapter": "HTML",
    "enabled": true,
    "config": {
      "method": "BOARD",
      "url": "https://kustartup.korea.ac.kr/",
      "link_selector": "a[href*=\"/program/programView.do?seq=\"]",
      "title_selector": ".detailTitle",
      "detail_selector": ".proView",
      "published_at_selector": ".postPeriod .addDay",
      "detect_period_conflicts": true,
      "require_detail_title": true,
      "html_parser": "html.parser",
      "max_pages": 1,
      "max_records": 40,
      "single_page_scope": true,
      "identity_query_keys": [
        "seq"
      ],
      "organization": "고려대학교 크림슨창업지원단",
      "organization_type": "UNIVERSITY",
      "allowed_hosts": [
        "kustartup.korea.ac.kr"
      ],
      "policy_status": "APPROVED",
      "weekly_direct": true,
      "validated_at": "2026-10-27"
    }
  },
  {
    "slug": "weekly-bizinfo-events",
    "name": "기업마당 공식 창업 행사·교육 공고",
    "adapter": "HTML",
    "enabled": true,
    "config": {
      "method": "BOARD",
      "url": "https://www.bizinfo.go.kr/sie/siea/selectSIEA430View.do",
      "link_selector": ".table_Type_1 a[href*=\"selectSIEA430Detail.do\"]",
      "title_selector": ".support_project_detail h2.title",
      "detail_selector": ".support_project_detail",
      "published_at_selector": ".support_project_detail .top_info li:first-child",
      "require_detail_title": true,
      "html_parser": "html.parser",
      "pagination_link_selector": "a[href*=\"selectSIEA430View.do?rows=15\"]",
      "pagination_query_key": "cpage",
      "pagination_first": 1,
      "max_pages": 5,
      "max_records": 50,
      "single_page_scope": false,
      "identity_query_keys": [
        "eventInfoId"
      ],
      "organization": "기업마당 공식 행사정보",
      "organization_type": "PUBLIC_INSTITUTION",
      "allowed_hosts": [
        "www.bizinfo.go.kr",
        "bizinfo.go.kr"
      ],
      "policy_status": "APPROVED",
      "weekly_direct": true,
      "validated_at": "2026-10-27"
    }
  },
  {
    "slug": "weekly-postech-aif-notices",
    "name": "POSTECH 산학협력단 · 창업지원팀 공지",
    "adapter": "HTML",
    "enabled": true,
    "config": {
      "max_pages": 5,
      "max_records": 50,
      "single_page_scope": false,
      "method": "BOARD",
      "url": "https://aif.postech.ac.kr/kor/support/notice.do",
      "pagination_link_selector": "a[href*=\"article.offset=\"]",
      "pagination_query_key": "article.offset",
      "pagination_first": 0,
      "pagination_step": 10,
      "link_selector": ".b-title-box a[href*=\"mode=view\"]",
      "detail_selector": ".b-content-box",
      "title_selector": ".b-title",
      "required_title_pattern": "창업지원팀",
      "application_link_selector": "a[href*=\"forms.gle/\"]",
      "submission_path_prefix": "/kor/support/notice.do",
      "organization": "POSTECH 창업지원팀",
      "organization_type": "UNIVERSITY",
      "allowed_hosts": [
        "aif.postech.ac.kr"
      ],
      "policy_status": "APPROVED",
      "weekly_direct": true,
      "identity_query_keys": [
        "mode",
        "articleNo"
      ],
      "validated_at": "2026-09-15"
    }
  },
  {
    "slug": "weekly-yonsei-notices",
    "name": "연세대 내부 모집 공지",
    "adapter": "HTML",
    "enabled": true,
    "config": {
      "max_pages": 5,
      "max_records": 50,
      "single_page_scope": false,
      "method": "BOARD",
      "url": "https://venture.yonsei.ac.kr/community/notice",
      "next_selector": "a.paging__link.next[href]",
      "link_selector": "a[href*=\"/community/notice/\"]",
      "detail_selector": ".covi-post-view__contents",
      "title_selector": ".covi-post-view__header-title",
      "required_title_pattern": "(?=.*(?:모집|신청|컨퍼런스))(?=.*(?:연세|캠퍼스타운|학생창업|실험실\\s*창업|START-UP\\s*렉토링))",
      "application_link_selector": "a[href*=\"forms.gle/\"]",
      "submission_path_prefix": "/community/notice/",
      "organization": "연세대학교 창업지원단",
      "organization_type": "UNIVERSITY",
      "allowed_hosts": [
        "venture.yonsei.ac.kr"
      ],
      "policy_status": "APPROVED",
      "weekly_direct": true,
      "validated_at": "2026-09-15"
    }
  },
  {
    "slug": "weekly-koef-recruitment",
    "name": "한국청년기업가정신재단 공식 모집 공지",
    "adapter": "HTML",
    "enabled": true,
    "config": {
      "method": "BOARD",
      "url": "https://www.koef.or.kr/board/notice_list.php",
      "pagination_link_selector": "a[href*=\"notice_list.php?page=\"]",
      "pagination_query_key": "page",
      "link_selector": "a[href*=\"notice_view.php?ARTICLE_SEQ=\"]",
      "detail_selector": "#CONTENT",
      "title_selector": "[data-radar-title]",
      "required_title_pattern": "^\\[모집\\]|학생.*창업.*모집",
      "submission_path_prefix": "/board/notice_view.php",
      "max_pages": 5,
      "max_records": 50,
      "single_page_scope": false,
      "organization": "한국청년기업가정신재단",
      "organization_type": "FOUNDATION",
      "allowed_hosts": [
        "www.koef.or.kr",
        "koef.or.kr"
      ],
      "policy_status": "APPROVED",
      "weekly_direct": true,
      "identity_query_keys": [
        "ARTICLE_SEQ"
      ],
      "validated_at": "2026-09-15"
    }
  },
  {
    "slug": "weekly-asan-notices",
    "name": "아산나눔재단·MARU 공식 모집 공지",
    "adapter": "HTML",
    "enabled": true,
    "config": {
      "method": "BOARD",
      "url": "https://asan-nanum.org/news/notice/",
      "next_selector": "a.nextpostslink[rel=\"next\"]",
      "max_pages": 5,
      "max_records": 50,
      "single_page_scope": false,
      "link_selector": "a[href*=\"asan-nanum.org/notice/\"]",
      "detail_selector": "article.content",
      "title_selector": "article.title h3",
      "require_detail_title": true,
      "required_title_pattern": "(?=.*(?:모집|참가\\s*신청|마루투어))(?=.*(?:MARU|마루|스타트업|창업|정주영))",
      "organization": "아산나눔재단",
      "organization_type": "FOUNDATION",
      "allowed_hosts": [
        "asan-nanum.org"
      ],
      "policy_status": "APPROVED",
      "weekly_direct": true,
      "validated_at": "2026-09-15"
    }
  }
]$sources$::jsonb)
  loop
    select to_jsonb(s) into previous from startup_radar.sources s where slug=proposed->>'slug';
    insert into startup_radar.sources(slug,name,adapter,enabled,config)
    values(proposed->>'slug',proposed->>'name',proposed->>'adapter',
           (proposed->>'enabled')::boolean,proposed->'config')
    on conflict(slug) do update set name=excluded.name,adapter=excluded.adapter,
      enabled=excluded.enabled,config=excluded.config;
    insert into startup_radar.admin_audit(action,entity_id,detail)
    values('SOURCE_COVERAGE_EXPANSION',proposed->>'slug',jsonb_build_object(
      'reason','Approved direct publishers, event channel and verified linked pagination',
      'previous',previous,'applied_source',proposed));
  end loop;
  -- Preserve unrelated API options, IDs and source health history.
  for api in select id,slug,config from startup_radar.sources where adapter in ('KSTARTUP','BIZINFO')
  loop
    update startup_radar.sources set config=coalesce(config,'{}'::jsonb)
      || '{"weekly_detail_enrichment":true}'::jsonb where id=api.id;
    insert into startup_radar.admin_audit(action,entity_id,detail)
    values('SOURCE_DETAIL_ENRICHMENT_ENABLED',api.slug,jsonb_build_object(
      'reason','Read official HTML facts without AI; preserve API identity and source facts',
      'previous_config',api.config,'weekly_detail_enrichment',true));
  end loop;
end
$coverage$;
