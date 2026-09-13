"""Official API contracts verified in docs/SOURCES.md and kstartup-openapi.json."""
import json
import os
import re
from urllib.parse import urljoin,unquote,urlsplit,parse_qs
from radar.adapters.longtail import HtmlAdapter
from radar.adapters.base import Candidate,AcquiredDetail,SourceFailure
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


def kstartup_portal_detail(row):
    value=row.get('detl_pg_url') or ''
    parsed=urlsplit(value)
    query=parse_qs(parsed.query)
    if (parsed.scheme=='https' and parsed.hostname in ('www.k-startup.go.kr','k-startup.go.kr')
        and parsed.path=='/web/contents/bizpbanc-ongoing.do' and query.get('schM')==['view']
        and query.get('pbancSn')==[str(row.get('pbanc_sn'))]):return value
    return None


def kstartup_period_time(day,text):
    """Only refine an API calendar date from labeled portal application periods."""
    if day is None:return day,'UNKNOWN'
    times=set()
    date_pattern=rf'(?<!\d){day.year}\s*(?:년|[./-])\s*0?{day.month}\s*(?:월|[./-])\s*0?{day.day}(?!\d)(?:\s*일)?'
    for section in re.finditer(r'(?:신청기간|접수기간)\s*[:：]?\s*([^\n]+)',text):
        for match in re.finditer(date_pattern+r'\s*\.?\s*(?:\([가-힣A-Za-z]+\))?\s*(\d{1,2}):(\d{2})(?!\d)',section.group(1)):
            hour,minute=map(int,match.groups())
            if hour<24 and minute<60:times.add((hour,minute))
    if len(times)==1:
        hour,minute=times.pop()
        return day.replace(hour=hour,minute=minute,second=0,microsecond=0),'DATETIME'
    return day,'DATE'


class KStartupApiAdapter(HtmlAdapter):
    endpoint='https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01'
    def fetch_detail(self,candidate):
        if kstartup_portal_detail(candidate.raw_metadata):
            self.config={**{'detail_selector':'.app_notice_details-wrap',
                            'document_selector':'a[name="downloadBtn"][href^="/afile/fileDownload/"]'},**self.config}
        try:return super().fetch_detail(candidate)
        except SourceFailure as error:
            if error.kind!='DETAIL_PARSE' or not kstartup_portal_detail(candidate.raw_metadata):raise
            # The official API can retain a notice whose portal body has vanished.
            # Preserve its structured facts, but never certify eligibility or ask
            # AI to guess the missing body/attachments. Access failures still fail.
            return AcquiredDetail(candidate.official_detail_url,
                html_text(candidate.raw_metadata.get('pbanc_ctnt') or ''),candidate.title,
                raw_metadata=candidate.raw_metadata,evidence_warning='DETAIL_UNAVAILABLE')
    def document_name(self,link):
        container=link.find_parent('li',class_='clear')
        filename=container.select_one('a.file_bg') if container else None
        return filename.get_text(' ',strip=True) if filename else super().document_name(link)
    def discover(self):
        key=os.environ.get(self.config.get('key_env','KSTARTUP_API_KEY'))
        if not key:raise SourceFailure('MISSING_CREDENTIAL','KSTARTUP_API_KEY is required')
        # Public-data portals supply encoded and decoded key forms. Requests
        # encodes params itself; decode once without treating literal '+' as space.
        key=unquote(key)
        maximum=self.config.get('max_pages',100);size=self.config.get('page_size',100)
        queries=self.config.get('current_title_queries',[])
        if not isinstance(queries,list) or len(queries)>5 or any(not isinstance(q,str) or not q.strip() or len(q)>100 for q in queries):
            raise SourceFailure('CONFIGURATION','At most five nonempty current-title queries are allowed')
        seen=set();limited=False
        # Current featured notices can predate the latest page. Query the same
        # official API, bound every query, and preserve publisher identity.
        for query in [None,*dict.fromkeys(queries)]:
            for page in range(1,maximum+1):
                data,_,_=self.http.get(self.endpoint,params={**{'serviceKey':key,'page':page,'perPage':size,'returnType':'json'},**({'cond[biz_pbanc_nm::LIKE]':query,'cond[rcrt_prgs_yn::EQ]':'Y'} if query else {})})
                payload=parse_json(data)
                if 'data' not in payload:raise SourceFailure('API_SCHEMA','K-Startup data field missing (possible API error)')
                rows=payload['data']
                if isinstance(rows,dict):rows=rows.get('data')
                if not isinstance(rows,list):raise SourceFailure('API_SCHEMA','K-Startup data must contain an array')
                for row in rows:
                    if not isinstance(row,dict) or not row.get('biz_pbanc_nm') or not row.get('pbanc_sn'):
                        raise SourceFailure('API_SCHEMA','Required K-Startup notice fields missing')
                    sid=str(row['pbanc_sn'])
                    if sid in seen:continue
                    seen.add(sid)
                    # The live API uses detl_pg_url for its canonical portal notice,
                    # even when the documented biz_aply_url field is null.
                    url=kstartup_portal_detail(row) or row.get('biz_aply_url') or row.get('biz_gdnc_url')
                    if not url:raise SourceFailure('API_SCHEMA','Official notice URL missing')
                    yield Candidate(self.source['slug'],str(row['pbanc_sn']),url,url,row['biz_pbanc_nm'],row,now().isoformat())
                total=payload.get('matchCount',payload.get('totalCount'))
                if not rows or len(rows)<size or total is not None and page*size>=int(total):break
            else:limited=True
        if limited:raise SourceFailure('PAGE_LIMIT','Discovery stopped at configured page limit; source is partial')
    def normalize(self,candidate,detail,documents):
        row=candidate.raw_metadata
        start=korean_date(row['pbanc_rcpt_bgng_dt']) if row.get('pbanc_rcpt_bgng_dt') else None
        end=korean_date(row['pbanc_rcpt_end_dt'],True) if row.get('pbanc_rcpt_end_dt') else None
        start_precision='DATE' if start else 'UNKNOWN'
        end_precision='DATE' if end else 'UNKNOWN'
        if kstartup_portal_detail(row):
            start,start_precision=kstartup_period_time(start,detail.text)
            end,end_precision=kstartup_period_time(end,detail.text)
        return Program(title=row['biz_pbanc_nm'],organization=row.get('pbanc_ntrp_nm') or row.get('sprv_inst') or self.source['name'],
            official_url=detail.url,application_url=None if kstartup_portal_detail(row) else row.get('detl_pg_url') or None,
            application_start_at=start,application_end_at=end,deadline_type='FIXED_DATE' if end else 'UNKNOWN',
            application_start_precision=start_precision,application_end_precision=end_precision,
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
