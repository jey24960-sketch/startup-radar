"""Official API contracts verified in docs/SOURCES.md and kstartup-openapi.json."""
import json
import os
import re
from urllib.parse import urljoin
from radar.adapters.longtail import HtmlAdapter
from radar.adapters.base import Candidate,SourceFailure
from radar.dates import korean_date
from radar.models import Program
from radar.documents import html_text
from core.clock import now


def parse_json(data):
    try:return json.loads(data)
    except (ValueError,UnicodeError):raise SourceFailure('API_JSON','API did not return valid JSON')


def parse_period(value):
    dates=re.findall(r'\b\d{8}\b',value or '')
    if len(dates)==2:return korean_date(dates[0]),korean_date(dates[1],True)
    return None,None


class KStartupApiAdapter(HtmlAdapter):
    endpoint='https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01'
    def discover(self):
        key=os.environ.get(self.config.get('key_env','KSTARTUP_API_KEY'))
        if not key:raise SourceFailure('MISSING_CREDENTIAL','KSTARTUP_API_KEY is required')
        maximum=self.config.get('max_pages',100);size=self.config.get('page_size',100)
        for page in range(1,maximum+1):
            data,_,_=self.http.get(self.endpoint,params={'serviceKey':key,'page':page,'perPage':size,'returnType':'json'})
            payload=parse_json(data)
            if 'data' not in payload:raise SourceFailure('API_SCHEMA','K-Startup data field missing (possible API error)')
            rows=payload['data']
            if isinstance(rows,dict):rows=rows.get('data')
            if not isinstance(rows,list):raise SourceFailure('API_SCHEMA','K-Startup data must contain an array')
            for row in rows:
                if not isinstance(row,dict) or not row.get('biz_pbanc_nm') or not row.get('pbanc_sn'):
                    raise SourceFailure('API_SCHEMA','Required K-Startup notice fields missing')
                url=row.get('biz_aply_url') or row.get('biz_gdnc_url')
                if not url:raise SourceFailure('API_SCHEMA','Official notice URL missing')
                yield Candidate(self.source['slug'],str(row['pbanc_sn']),url,url,row['biz_pbanc_nm'],row,now().isoformat())
            total=payload.get('matchCount',payload.get('totalCount'))
            if not rows or len(rows)<size or total is not None and page*size>=int(total):return
        raise SourceFailure('PAGE_LIMIT','Discovery stopped at configured page limit; source is partial')
    def normalize(self,candidate,detail,documents):
        row=candidate.raw_metadata
        start=korean_date(row['pbanc_rcpt_bgng_dt']) if row.get('pbanc_rcpt_bgng_dt') else None
        end=korean_date(row['pbanc_rcpt_end_dt'],True) if row.get('pbanc_rcpt_end_dt') else None
        return Program(title=row['biz_pbanc_nm'],organization=row.get('pbanc_ntrp_nm') or row.get('sprv_inst') or self.source['name'],
            official_url=detail.url,application_url=row.get('detl_pg_url') or None,
            application_start_at=start,application_end_at=end,deadline_type='FIXED_DATE' if end else 'UNKNOWN',
            application_start_precision='DATE' if start else 'UNKNOWN',application_end_precision='DATE' if end else 'UNKNOWN',
            applicant_summary=row.get('aply_trgt_ctnt') or row.get('aply_trgt'),support_summary=html_text(row.get('pbanc_ctnt','')),
            program_types=[row['supt_biz_clsfc']] if row.get('supt_biz_clsfc') else [],
            document_hashes=[d['content_hash'] for d in documents if d.get('content_hash')])


class BizInfoApiAdapter(HtmlAdapter):
    endpoint='https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do'
    def discover(self):
        key=os.environ.get(self.config.get('key_env','BIZINFO_API_KEY'))
        if not key:raise SourceFailure('MISSING_CREDENTIAL','BIZINFO_API_KEY is required')
        size=self.config.get('page_size',100);maximum=self.config.get('max_pages',100)
        for page in range(1,maximum+1):
            data,_,_=self.http.get(self.endpoint,params={'crtfcKey':key,'dataType':'json','pageUnit':size,'pageIndex':page,'searchCnt':0})
            payload=parse_json(data)
            envelope=payload.get('jsonArray') if isinstance(payload,dict) else None
            if isinstance(envelope,dict):rows=envelope.get('item')
            elif isinstance(envelope,list):rows=envelope
            else:raise SourceFailure('API_SCHEMA','BizInfo jsonArray missing (possible API error)')
            if not isinstance(rows,list):raise SourceFailure('API_SCHEMA','BizInfo items must be an array')
            for row in rows:
                title=row.get('pblancNm') or row.get('title');url=row.get('pblancUrl') or row.get('link');sid=row.get('pblancId') or row.get('seq')
                if not title or not url or not sid:raise SourceFailure('API_SCHEMA','Required BizInfo notice fields missing')
                url=urljoin('https://www.bizinfo.go.kr',url)
                yield Candidate(self.source['slug'],sid,url,url,title,row,now().isoformat())
            if not rows or len(rows)<size:return
            total=rows[0].get('totCnt')
            if total is not None and page*size>=int(total):return
        raise SourceFailure('PAGE_LIMIT','Discovery reached page limit; source is partial')
    def fetch_detail(self,candidate):
        detail=super().fetch_detail(candidate)
        for url_key,name_key in [('flpthNm','fileNm'),('printFlpthNm','printFileNm')]:
            urls=candidate.raw_metadata.get(url_key)
            if not urls:continue
            # The live API joins parallel attachment URL/name lists with '@'.
            # Keep empty positions so a missing filename cannot shift attribution.
            names=(candidate.raw_metadata.get(name_key) or '').split('@')
            for index,url in enumerate(urls.split('@')):
                if not url.strip():continue
                name=names[index].strip() if index<len(names) else ''
                detail.document_urls.append((urljoin(detail.url,url.strip()),name or 'attachment'))
        return detail
    def normalize(self,candidate,detail,documents):
        row=candidate.raw_metadata;start,end=parse_period(row.get('reqstBeginEndDe') or row.get('reqstDt'))
        return Program(title=candidate.title,organization=row.get('jrsdInsttNm') or row.get('author') or self.source['name'],
            official_url=detail.url,application_url=row.get('rceptEngnHmpgUrl') or None,
            application_start_at=start,application_end_at=end,deadline_type='FIXED_DATE' if end else 'UNKNOWN',
            application_start_precision='DATE' if start else 'UNKNOWN',application_end_precision='DATE' if end else 'UNKNOWN',
            applicant_summary=row.get('trgetNm'),support_summary=html_text(row.get('bsnsSumryCn') or row.get('description') or ''),
            program_types=[row.get('pldirSportRealmLclasCodeNm') or row.get('lcategory') or 'UNKNOWN'],
            document_hashes=[d['content_hash'] for d in documents if d.get('content_hash')])
