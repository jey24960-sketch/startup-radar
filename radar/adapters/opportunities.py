"""Reviewed, bounded official channels. Search/newsletter inputs never publish here."""
import re
import time
from urllib.parse import urlsplit,urljoin
from bs4 import BeautifulSoup
from radar.adapters.base import Candidate,AcquiredDetail,SourceFailure
from radar.adapters.longtail import RssAdapter,BrowserAdapter
from radar.identity import normalize_url,digest
from radar.models import Program
from radar.opportunity_facts import classify,labeled_period,explicit_date,EXCLUDED_TITLE
from core.clock import now


class ChannelCoverage:
    def __init__(self,config):self.config=config;self.pages=0;self.discovered=0;self.complete=False;self.rechecks=0;self.excluded=0
    def report(self):
        return dict(scope='CONFIGURED_CHANNEL',pages_requested=self.pages,page_cap=self.config.get('max_pages',2),
                    fetched_unique_records=self.discovered,pagination_complete=self.complete,
                    active_detail_rechecks=self.rechecks,non_recruitment_excluded=self.excluded,
                    scope_note='Configured listing pages and capped active-detail watchlist only; not institution-wide coverage')


class OfficialChannelAdapter:
    def __init__(self,source,http):
        self.source=source;self.http=http;self.config=source['config'];self.pagination=ChannelCoverage(self.config)
        self.started=time.monotonic();self.last_request=0;self.requests=0;self.cache={}
    def get(self,url):
        if self.requests>=60 or time.monotonic()-self.started>240:raise SourceFailure('CHANNEL_BUDGET','Channel time/request budget reached')
        wait=1-(time.monotonic()-self.last_request)
        if wait>0:time.sleep(wait)
        self.requests+=1
        try:
            data,mime,final=self.http.get(url)
            if len(data)>3_000_000:raise SourceFailure('SIZE_LIMIT','HTML/RSS channel limit is 3 MB')
            return data,mime,final
        finally:self.last_request=time.monotonic()
    def discover(self):
        if self.config.get('policy_status')!='APPROVED':raise SourceFailure('POLICY_REVIEW','Channel policy/official ownership approval required')
        method=self.config.get('method','BOARD');seen=set();limit=self.config.get('max_records',30)
        if type(limit) is not int or not 1<=limit<=100:raise SourceFailure('CONFIGURATION','max_records must be 1..100')
        if method=='PAGE':
            self.pagination.complete=True;self.pagination.pages=1;self.pagination.discovered=1
            yield Candidate(self.source['slug'],normalize_url(self.config['url']),self.config['url'],self.config['url'],self.config.get('title',self.source['name']))
            return
        if method=='NEWSLETTER':raise SourceFailure('NOT_CONFIGURED','Dedicated authorized newsletter inbox is not connected')
        if method not in ('BOARD','RSS','BROWSER'):raise SourceFailure('NOT_CONFIGURED','Requested channel has no implemented adapter')
        max_pages=self.config.get('max_pages',2)
        if type(max_pages) is not int or not 1<=max_pages<=5:raise SourceFailure('CONFIGURATION','max_pages must be 1..5')
        url=self.config['url'];pages_seen=set()
        for _ in range(max_pages):
            if url in pages_seen:raise SourceFailure('PAGINATION_STALLED','Repeated listing page')
            pages_seen.add(url);self.pagination.pages+=1
            if method=='RSS':
                # Existing defused XML parser; raw provider data never executes.
                adapter=RssAdapter({**self.source,'config':{**self.config,'url':url}},self)
                candidates=list(adapter.discover());next_url=None
            else:
                data,_,final=self.get(url) if method!='BROWSER' else BrowserAdapter(self.source,self.http)._render(url)
                soup=BeautifulSoup(data,'lxml');selector=self.config.get('link_selector')
                if not selector:raise SourceFailure('CONFIGURATION','Reviewed notice selector required')
                candidates=[]
                for link in soup.select(selector):
                    href=link.get('href','')
                    if not href or href.startswith(('#','javascript:')):continue
                    target=urljoin(final,href)
                    if urlsplit(target).scheme!='https':continue
                    self.http.validate_url(target)
                    candidates.append(Candidate(self.source['slug'],normalize_url(target),final,target,link.get_text(' ',strip=True),{'list_url':final},now().isoformat()))
                nxt=soup.select_one(self.config['next_selector']) if self.config.get('next_selector') else None
                next_url=urljoin(final,nxt.get('href','')) if nxt and nxt.get('href') else None
                if not candidates and not (self.config.get('empty_marker') and self.config['empty_marker'] in soup.get_text()):
                    raise SourceFailure('LIST_PARSE','No notice links and no verified empty-list marker')
            for candidate in candidates:
                if candidate.official_detail_url in seen:continue
                seen.add(candidate.official_detail_url)
                if EXCLUDED_TITLE.search(candidate.title):self.pagination.excluded+=1;continue
                if self.config.get('required_title_pattern') and not re.search(self.config['required_title_pattern'],candidate.title,re.I):
                    self.pagination.excluded+=1;continue
                if self.pagination.discovered>=limit:raise SourceFailure('PAGE_LIMIT','Configured record cap reached')
                self.pagination.discovered+=1
                yield candidate
            if not next_url:
                self.pagination.complete=bool(self.config.get('single_page_scope')) or method=='RSS' or bool(self.config.get('next_selector'))
                break
            url=next_url
        else:raise SourceFailure('PAGE_LIMIT','Configured page cap reached before final listing page')
        # A bounded homepage slice must not be described as a full institution scan.
        if not self.pagination.complete:raise SourceFailure('PAGE_LIMIT','Listing scope is bounded; pagination completeness unverified')
    def fetch_detail(self,candidate):
        if self.config.get('policy_status')!='APPROVED':raise SourceFailure('POLICY_REVIEW','Official channel approval required')
        data,_,url=self.get(candidate.official_detail_url) if self.config.get('method')!='BROWSER' else BrowserAdapter(self.source,self.http)._render(candidate.official_detail_url)
        soup=BeautifulSoup(data,'lxml')
        title_node=soup.select_one(self.config.get('title_selector','h1'))
        title=(title_node.get(self.config['title_attribute'],'') if self.config.get('title_attribute') and title_node else title_node.get_text(' ',strip=True) if title_node else candidate.title)
        body=soup.select_one(self.config.get('detail_selector','main'))
        if body is None:raise SourceFailure('DETAIL_PARSE','Reviewed body selector no longer matches')
        for node in body.select('script,style,nav,header,footer,form,input,textarea'):node.decompose()
        text=body.get_text('\n',strip=True)
        if len(text)<40:raise SourceFailure('DETAIL_PARSE','Official page has insufficient readable text; rendering or document review needed')
        if len(text)>120000:raise SourceFailure('SIZE_LIMIT','Notice text exceeds the 120k character limit')
        metadata=dict(candidate.raw_metadata)
        if self.config.get('rolling_selector'):
            marker=body.select_one(self.config['rolling_selector'])
            metadata['rolling_marker']=marker.get_text(' ',strip=True) if marker else None
        links=[]
        for link in body.select('a[href]'):
            label=link.get_text(' ',strip=True)
            if re.search(r'뉴스레터|소식\s*받기|구독|newsletter',label,re.I):continue
            if re.search(r'신청|지원하기|접수|apply',label,re.I):
                target=urljoin(url,link['href']);parts=urlsplit(target)
                if parts.scheme=='https' and parts.hostname and not parts.username and not parts.password:
                    # Validate public DNS/ports even for links we only store.
                    # This never grants permission to fetch a new form domain.
                    try:self.http.validate_url(target,require_allowlisted=False)
                    except SourceFailure:continue
                    links.append({'url':target,'text':label[:100],'linked_from':url})
        metadata['official_application_links']=links
        metadata['detail_checked_at']=now().isoformat()
        return AcquiredDetail(url,text,title or candidate.title,[],metadata)
    def fetch_documents(self,detail):return []
    def normalize(self,candidate,detail,documents):
        title=detail.title
        facts=classify(title,detail.text,{**self.config,'official_url':detail.url})
        links=detail.raw_metadata.get('official_application_links',[])
        # Multiple distinct forms are ambiguous; do not silently choose a cohort/track.
        urls={x['url'] for x in links}
        application_url=next(iter(urls)) if len(urls)==1 else None
        if application_url:
            facts.application_link_verified=True;facts.evidence['application_url']=links[0]
        elif len(urls)>1:facts.review_reasons.append('MULTIPLE_APPLICATION_LINKS')
        else:facts.review_reasons.append('APPLICATION_LINK_UNKNOWN')
        start,end,sp,ep,period=labeled_period(detail.text,facts.year)
        if period:facts.evidence['application_period']={'text':period,'url':detail.url}
        rolling=re.search(r'(?:상시\s*(?:모집|접수)|연중\s*(?:모집|접수)|applications?[^\n]{0,50}(?:year-round|year round))',detail.text,re.I)
        scoped_rolling=detail.raw_metadata.get('rolling_marker')=='상시'
        if rolling or scoped_rolling:
            facts.evidence['rolling']={'text':rolling[0] if rolling else '상시','url':detail.url};facts.recruitment_confirmed=True
        if facts.recruitment_confirmed:
            facts.review_reasons=[r for r in facts.review_reasons if r!='RECRUITMENT_UNCONFIRMED']
        if self.config.get('official_application_page') and application_url:
            facts.recruitment_confirmed=True
            facts.review_reasons=[r for r in facts.review_reasons if r!='RECRUITMENT_UNCONFIRMED']
        if self.config.get('method')=='PAGE' and not end and not start and not rolling and not scoped_rolling and not (self.config.get('official_application_page') and application_url):
            facts.recruitment_confirmed=False
            if 'RECRUITMENT_UNCONFIRMED' not in facts.review_reasons:facts.review_reasons.append('RECRUITMENT_UNCONFIRMED')
        if not end and not rolling and not scoped_rolling:facts.review_reasons.append('DEADLINE_UNKNOWN')
        for label,key in [('행사\s*일시|개최\s*일시','event_start_at')]:
            match=re.search(r'(?:'+label+r')\s*[:：]?\s*([^\n]{5,100})',detail.text)
            if match:
                value,_=explicit_date(match[1])
                if value:setattr(facts,key,value.isoformat());facts.evidence[key]={'text':match[0],'url':detail.url}
        # Fixed pages may contain an old HTML title. Only an explicit current heading
        # is accepted; absent cohort/period remains a review item, never "open".
        if self.config.get('method')=='PAGE' and not facts.cohort and not rolling and not scoped_rolling:facts.review_reasons.append('COHORT_UNKNOWN')
        target=facts.evidence.get('target',{}).get('text')
        if self.config.get('organizer_unverified'):
            facts.organization_type='UNKNOWN'
            facts.review_reasons.append('ORGANIZER_UNKNOWN')
        program=Program(title=title,organization=self.config['organization'],official_url=detail.url,
            application_url=application_url,application_start_at=start,application_end_at=end,
            application_start_precision=sp,application_end_precision=ep,
            deadline_type='ROLLING' if rolling or scoped_rolling else 'FIXED_DATE' if end else 'UNKNOWN',
            applicant_summary=target,support_summary=detail.text[:500],evidence_complete=False,
            opportunity=facts.model_dump())
        # Stable URL, new cohort/participation/region = a distinct recruitment.
        candidate.source_program_id=digest({'url':normalize_url(detail.url),'cohort':facts.cohort,'year':facts.year,
            'participation':facts.participation,'regions':facts.regions})
        return program
