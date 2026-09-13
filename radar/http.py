"""Bounded, identifiable fetching. Robots/blocks are failures, never bypassed."""
import ipaddress
import socket
import time
from urllib.parse import urlsplit,urljoin
from urllib.robotparser import RobotFileParser
import requests
from radar.adapters.base import SourceFailure


class SafeHttp:
    def __init__(self,allowed_hosts,max_bytes=20_000_000,timeout=20):
        self.allowed_hosts=set(allowed_hosts);self.max_bytes=max_bytes;self.timeout=timeout
        self.session=requests.Session()
        self.session.headers['User-Agent']='StartupRadar/2.0 (+public startup notice indexing)'
        self.robots={}

    def validate_url(self,url):
        p=urlsplit(url)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
            raise SourceFailure('UNSAFE_URL','HTTPS public URLs required')
        if p.hostname not in self.allowed_hosts:
            raise SourceFailure('UNAPPROVED_HOST','Host must be configured for this source')
        try: addresses=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
        except OSError: raise SourceFailure('DNS','Source hostname could not be resolved',True)
        if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise SourceFailure('UNSAFE_ADDRESS','Private network targets are not allowed')

    def _request(self,url,params=None,check_robots=True):
        for _ in range(6):
            self.validate_url(url)
            if check_robots: self.check_robots(url)
            try:
                with self.session.get(url,params=params,timeout=self.timeout,stream=True,allow_redirects=False) as response:
                    if response.status_code in (301,302,303,307,308):
                        url=urljoin(url,response.headers.get('Location',''));params=None;continue
                    if response.status_code in (401,403): raise SourceFailure('BLOCKED','Source denied access')
                    if response.status_code==429: raise SourceFailure('RATE_LIMIT','Source rate limit',True)
                    if response.status_code==404: raise SourceFailure('NOT_FOUND','Source not found')
                    if response.status_code>=400: raise SourceFailure('HTTP',f'HTTP {response.status_code}',response.status_code>=500,response.status_code)
                    if int(response.headers.get('Content-Length','0'))>self.max_bytes: raise SourceFailure('SIZE_LIMIT','Response too large')
                    data=bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data)>self.max_bytes: raise SourceFailure('SIZE_LIMIT','Response too large')
                    return bytes(data),response.headers.get('Content-Type','').split(';')[0].lower(),url
            except requests.Timeout: raise SourceFailure('TIMEOUT','Source request timed out',True)
            except requests.RequestException: raise SourceFailure('NETWORK','Source request failed',True)
        raise SourceFailure('REDIRECT_LIMIT','Too many redirects')

    def check_robots(self,url):
        p=urlsplit(url);origin=f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            try:
                data,_,_=self._request(origin+'/robots.txt',check_robots=False)
                parser=RobotFileParser();parser.parse(data.decode('utf-8',errors='replace').splitlines())
                self.robots[origin]=parser
            except SourceFailure as failure:
                # RFC 9309 2.3.1.3 permits access when robots is unavailable (4xx).
                # Retain conservative denial for authentication/access failures,
                # throttling, network errors and server errors.
                if failure.kind=='NOT_FOUND' or (failure.kind=='HTTP' and failure.http_status in (400,410)):
                    self.robots[origin]=None
                else: raise SourceFailure('ROBOTS_UNAVAILABLE','Cannot verify robots policy',failure.retryable)
        parser=self.robots[origin]
        if parser and not parser.can_fetch('StartupRadar',url): raise SourceFailure('ROBOTS_DENIED','Robots policy disallows this resource')

    def get(self,url,params=None):
        for attempt in range(2):
            try:return self._request(url,params)
            except SourceFailure as error:
                if attempt or not error.retryable or error.kind not in ('DNS','NETWORK','TIMEOUT','HTTP','ROBOTS_UNAVAILABLE'):raise
                # Retry one transient acquisition failure. The second attempt
                # still rechecks robots/hosts and preserves any final failure.
                time.sleep(2)
