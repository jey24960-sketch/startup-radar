"""Long-tail discovery. Source selectors/configuration live outside the pipeline."""
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from radar.adapters.base import SourceAdapter,Candidate,AcquiredDetail,SourceFailure
from radar.documents import html_text,fetch_document
from radar.models import Program
from core.clock import now

DOCUMENT_EXTENSIONS=('.pdf','.hwp','.hwpx','.docx')


class HtmlAdapter(SourceAdapter):
    def __init__(self,source,http):self.source=source;self.http=http;self.config=source['config']
    def discover(self):
        selector=self.config.get('link_selector')
        if not selector:raise SourceFailure('CONFIGURATION','HTML discovery requires an explicit notice link selector')
        data,_,url=self.http.get(self.config['url'])
        soup=BeautifulSoup(data,'lxml');seen=set()
        for link in soup.select(selector):
            href=link.get('href','')
            if not href or href.startswith(('javascript:','#')):continue
            target=urljoin(url,href)
            if target in seen:continue
            seen.add(target)
            yield Candidate(self.source['slug'],None,target,target,link.get_text(' ',strip=True),{'list_url':url},now().isoformat())
    def fetch_detail(self,candidate):
        data,_,url=self.http.get(candidate.official_detail_url)
        soup=BeautifulSoup(data,'lxml')
        selector=self.config.get('detail_selector')
        body=soup.select_one(selector) if selector else soup.find('main') or soup.find('article') or soup.body or soup
        if body is None:raise SourceFailure('DETAIL_PARSE','Configured detail selector not found')
        attachments=[]
        for link in body.select('a[href]'):
            target=urljoin(url,link['href']);name=link.get_text(' ',strip=True)
            if urlsplit(target).path.lower().endswith(DOCUMENT_EXTENSIONS) or name.lower().endswith(DOCUMENT_EXTENSIONS):
                attachments.append((target,name or urlsplit(target).path.rsplit('/',1)[-1]))
        return AcquiredDetail(url,html_text(str(body)),candidate.title,attachments,candidate.raw_metadata)
    def fetch_documents(self,detail):
        return [fetch_document(self.http,url,name) for url,name in dict(detail.document_urls).items()]
    def normalize(self,candidate,detail,documents):
        return Program(title=candidate.title or detail.title,organization=self.config.get('organization',self.source['name']),
            official_url=detail.url,applicant_summary=None,support_summary=detail.text[:1000],
            document_hashes=[d['content_hash'] for d in documents if d.get('content_hash')],evidence_complete=False)


class RssAdapter(HtmlAdapter):
    def discover(self):
        data,_,url=self.http.get(self.config['url'])
        try:root=ET.fromstring(data)
        except Exception:raise SourceFailure('RSS_PARSE','RSS/Atom could not be parsed')
        local=lambda tag:tag.split('}')[-1]
        if local(root.tag) not in ('rss','feed','RDF'):raise SourceFailure('RSS_SCHEMA','Expected RSS/Atom feed')
        for item in root.iter():
            if local(item.tag) not in ('item','entry'):continue
            values={local(child.tag):''.join(child.itertext()).strip() for child in item}
            links=[child for child in item if local(child.tag)=='link']
            target=next((x.attrib.get('href') or x.text for x in links if x.attrib.get('rel','alternate')=='alternate'),None)
            if not target:continue
            target=urljoin(url,target.strip())
            yield Candidate(self.source['slug'],values.get('guid') or values.get('id'),target,target,
                values.get('title') or '제목 확인 필요',dict(values,feed_url=url),now().isoformat())


class BrowserAdapter(HtmlAdapter):
    def _render(self,url):
        self.http.validate_url(url);self.http.check_robots(url)
        try:from playwright.sync_api import sync_playwright
        except ImportError:raise SourceFailure('DEPENDENCY','Install Playwright and its Chromium browser')
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                page=browser.new_page(user_agent='StartupRadar/2.0 public notice reader')
                blocked=[]
                def route_request(route):
                    if route.request.resource_type in ('image','font','media'):return route.abort()
                    try:
                        self.http.validate_url(route.request.url);self.http.check_robots(route.request.url)
                        route.continue_()
                    except SourceFailure as error:
                        blocked.append(error.kind);route.abort()
                page.route('**/*',route_request)
                response=page.goto(url,wait_until='domcontentloaded',timeout=20000)
                if response is None or response.status>=400:raise SourceFailure('BROWSER_BLOCKED','Rendered source did not load')
                selector=self.config.get('ready_selector')
                if selector:page.wait_for_selector(selector,timeout=10000)
                text=page.content()
                if any(term in text.lower() for term in ('g-recaptcha','h-captcha','cf-chl-','verify you are human')):
                    raise SourceFailure('CAPTCHA','Access challenge detected; no bypass attempted')
                return text.encode(), 'text/html', page.url
            finally:browser.close()
    def discover(self):
        original=self.http.get
        self.http.get=lambda url,params=None:self._render(url)
        try:yield from super().discover()
        finally:self.http.get=original
    def fetch_detail(self,candidate):
        original=self.http.get;self.http.get=lambda url,params=None:self._render(url)
        try:return super().fetch_detail(candidate)
        finally:self.http.get=original


class SearchDiscoveryAdapter(HtmlAdapter):
    """Provider is explicitly injected; never scrapes consumer search pages."""
    def __init__(self,source,http,provider=None):super().__init__(source,http);self.provider=provider
    def discover(self):
        if self.provider is None:raise SourceFailure('NOT_CONFIGURED','Search discovery disabled: no provider configured')
        allowed=set(self.config.get('official_hosts',[]))
        for query in self.config.get('queries',[]):
            for result in self.provider.search(query):
                if urlsplit(result['url']).hostname not in allowed:continue
                yield Candidate(self.source['slug'],None,result['url'],result['url'],result['title'],
                                {'provider':self.provider.name,'query':query},now().isoformat())
