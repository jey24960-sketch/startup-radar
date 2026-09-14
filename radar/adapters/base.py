from dataclasses import dataclass,field
from typing import Any
from urllib.parse import urlsplit,urlunsplit


@dataclass
class SourceFailure(Exception):
    kind: str
    message: str
    retryable: bool=False
    http_status: int | None=None
    reason_code: str | None=None
    cause_kind: str | None=None
    def __str__(self): return f'{self.kind}: {self.message}'

    def record(self, *, stage=None, url=None):
        aliases={'DNS':'DNS_ERROR','TIMEOUT':'READ_TIMEOUT','NETWORK':'NETWORK_ERROR',
                 'BLOCKED':'HTTP_4XX','ROBOTS_DENIED':'ROBOTS_DISALLOWED',
                 'ROBOTS_UNAVAILABLE':'ROBOTS_HTTP_ERROR','SIZE_LIMIT':'RESPONSE_TOO_LARGE',
                 'REDIRECT_LIMIT':'INVALID_REDIRECT','UNAPPROVED_HOST':'HOST_NOT_ALLOWED'}
        reason=self.reason_code or aliases.get(self.kind,self.kind)
        if self.kind=='HTTP' and self.http_status:
            reason='HTTP_5XX' if self.http_status>=500 else 'HTTP_4XX'
        result={'kind':self.kind,'reason_code':reason,'message':self.message,
                'retryable':self.retryable}
        if self.http_status is not None:result['http_status']=self.http_status
        if self.cause_kind:result['cause_kind']=self.cause_kind
        if stage:result['stage']=stage
        if url:
            # Never serialize API keys, credentials or fragments in diagnostics.
            try:
                parts=urlsplit(url)
                result['url']=urlunsplit((parts.scheme,parts.hostname or '',parts.path,'',''))
            except (ValueError,TypeError):result['url']='[invalid URL]'
        return result


@dataclass
class Candidate:
    source: str
    source_program_id: str | None
    discovery_url: str
    official_detail_url: str
    title: str
    raw_metadata: dict = field(default_factory=dict)
    discovered_at: str | None = None


@dataclass
class AcquiredDetail:
    url: str
    text: str
    title: str
    document_urls: list[tuple[str,str]] = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)
    evidence_warning: str | None = None


class SourceAdapter:
    def discover(self): raise NotImplementedError
    def fetch_detail(self,candidate): raise NotImplementedError
    def fetch_documents(self,detail): raise NotImplementedError
    def normalize(self,candidate,detail,documents): raise NotImplementedError
