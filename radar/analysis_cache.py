"""Cache only successful extraction, keyed by actual evidence and extractor version."""
from psycopg.types.json import Jsonb
from radar.identity import digest
from radar.models import Program


def extract_cached(db, extractor, program, detail, documents, source_id, metadata):
    # Include normalized structured facts, text and stable document content/status.
    # Ignore acquisition timestamps; a changed attachment, parser result, extractor
    # schema or model must invalidate the cached analysis.
    key=digest({'source_id':str(source_id),'normalized':program.model_dump(mode='json'),
        'detail':detail.text,'documents':[{k:d.get(k) for k in
        ('original_url','content_hash','extracted_text','fetch_status','extraction_status')}
        for d in sorted(documents,key=lambda d:d['original_url'])],
        'model':getattr(extractor,'model',None),'version':getattr(extractor,'version',None),
        'extractor':type(extractor).__module__+'.'+type(extractor).__qualname__})
    with db.transaction() as c:
        # Serializes concurrent identical analysis without blocking other inputs.
        c.execute('select pg_advisory_xact_lock(%s)',(int(key[:15],16),))
        cached=c.execute('select normalized,metadata from startup_radar.extraction_cache where input_hash=%s',(key,)).fetchone()
        if cached:
            metadata.update(cached['metadata'],cache_hit=True,input_hash=key)
            return Program.model_validate(cached['normalized'])
        result=extractor.extract(program,detail,documents,source_id)
        metadata.update(cache_hit=False,input_hash=key,review_flags=getattr(extractor,'review_flags',[]))
        c.execute('insert into startup_radar.extraction_cache(input_hash,normalized,metadata) values(%s,%s,%s)',
            (key,Jsonb(result.model_dump(mode='json')),Jsonb(metadata)))
        return result
