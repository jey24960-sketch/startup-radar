"""Explicit provider retries and measured usage, without raw prompts/errors in logs."""
import time
import anthropic
from radar.adapters.base import SourceFailure

REQUEST_TIMEOUT=90.0
MAX_REQUESTS=2


def classify_error(error):
    status=getattr(error,'status_code',None)
    if isinstance(error,anthropic.APITimeoutError):return 'AI_TIMEOUT',True
    if isinstance(error,anthropic.APIConnectionError):return 'AI_CONNECTION',True
    if status==429:return 'AI_RATE_LIMIT',True
    if status in (408,409) or status is not None and 500<=status<=599:return 'AI_SERVER',True
    if status in (401,403):return 'AI_CREDENTIALS',False
    return 'AI_REQUEST',False


def request(client,metrics,**payload):
    metrics.update(requests=[],request_count=0,retry_calls=0,successful_calls=0,failed_calls=0,
                   input_tokens=0,output_tokens=0,cache_read_input_tokens=0,cache_creation_input_tokens=0,
                   usage_unknown_calls=0,timeout_seconds=REQUEST_TIMEOUT,max_requests=MAX_REQUESTS)
    # Disable the SDK's hidden retries even when a caller supplies a real client.
    if isinstance(client,anthropic.Anthropic):client=client.with_options(max_retries=0,timeout=REQUEST_TIMEOUT)
    for number in range(1,MAX_REQUESTS+1):
        started=time.monotonic()
        row={'attempt':number,'input_tokens':None,'output_tokens':None}
        metrics['request_count']+=1
        metrics['retry_calls']+=number>1
        try:
            response=client.messages.create(**payload,timeout=REQUEST_TIMEOUT)
        except anthropic.APIError as error:
            reason,retryable=classify_error(error)
            row.update(status='FAILED',reason_code=reason,http_status=getattr(error,'status_code',None),
                       latency_ms=round((time.monotonic()-started)*1000))
            metrics['requests'].append(row)
            metrics['failed_calls']+=1;metrics['usage_unknown_calls']+=1
            if retryable and number<MAX_REQUESTS:
                time.sleep(2**number)
                continue
            raise SourceFailure(reason,'AI provider request failed; see measured attempt metadata',retryable) from None
        usage=getattr(response,'usage',None)
        row.update(status='SUCCESS',model=getattr(response,'model',None),
                   latency_ms=round((time.monotonic()-started)*1000))
        for name in ('input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens'):
            value=getattr(usage,name,None)
            row[name]=value if type(value) is int and value>=0 else None
            if row[name] is not None:metrics[name]+=row[name]
        if row['input_tokens'] is None or row['output_tokens'] is None:metrics['usage_unknown_calls']+=1
        metrics['successful_calls']+=1;metrics['requests'].append(row)
        return response
