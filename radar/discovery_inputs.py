"""Optional search/newsletter candidate interfaces. No implicit mailbox access."""
from typing import Protocol
from itertools import islice
from urllib.parse import urlsplit
from radar.adapters.base import SourceFailure


class SearchProvider(Protocol):
    def search(self,query: str,limit: int): ...


class NewsletterProvider(Protocol):
    def messages(self,inbox_id: str,senders: list[str],limit: int): ...


def candidates(provider=None,*,kind,queries=(),inbox_id=None,senders=(),authorized=False):
    if provider is None:return {'state':'UNCONNECTED','candidates':[]}
    if kind=='NEWSLETTER' and (not authorized or not inbox_id or not senders):
        raise SourceFailure('INBOX_NOT_AUTHORIZED','An explicitly authorized dedicated inbox and official senders are required')
    rows=[]
    if kind=='SEARCH':
        for query in islice(queries,5):rows.extend(islice(provider.search(query,limit=10),10))
    elif kind=='NEWSLETTER':
        for message in islice(provider.messages(inbox_id,list(senders),limit=20),20):
            if message.get('sender') not in senders or not message.get('authenticated_sender'):continue
            rows.extend(message.get('links',[])[:5])
    else:raise ValueError('Unknown discovery input')
    result={}
    for row in rows[:100]:
        try:parts=urlsplit(row['url'])
        except (ValueError,KeyError,TypeError):continue
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:continue
        result[row['url']]={'url':row['url'],'description':str(row.get('title',''))[:1000]}
    return {'state':'CANDIDATES_ONLY','candidates':list(result.values())}


def save_candidates(db,result,origin):
    if origin not in ('SEARCH','NEWSLETTER'):raise ValueError('External candidate origin required')
    with db.transaction() as c:
        for row in result['candidates']:
            c.execute('insert into startup_radar.opportunity_submissions(origin,official_url,description) select %s,%s,%s '
                'where not exists(select 1 from startup_radar.opportunity_submissions where official_url=%s and origin=%s)',
                (origin,row['url'],row['description'],row['url'],origin))
    return {'state':result['state'],'candidates':len(result['candidates']),'published':0,'hosts_added':0}
