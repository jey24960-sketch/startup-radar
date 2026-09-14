"""Read-only, bounded live check. No database, .env, AI or messaging access."""
import argparse,json
from pathlib import Path
from dataclasses import asdict
from core.clock import now
from radar.ingestion import build_adapter
from radar.adapters.base import SourceFailure

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='work/expanded-channels.json')
    parser.add_argument('--institution',action='append');parser.add_argument('--sample-size',type=int,default=3)
    args=parser.parse_args()
    if not 1<=args.sample_size<=5:parser.error('sample-size must be 1..5')
    catalogue=json.loads(Path('institutions.json').read_text(encoding='utf8'));results=[]
    for org in catalogue['institutions']:
        if org['policy_status']!='APPROVED' or (args.institution and org['slug'] not in args.institution):continue
        if not args.institution and 'previous_review' not in org:continue
        for channel in org['channels']:
            if channel['config']['method']=='REQUEST':continue
            source={'slug':channel['slug'],'name':channel['name'],'adapter':'HTML','config':{**channel['config'],'organization':org['name'],'organization_type':org['kind'],'opportunity_channel':True,'allowed_hosts':org['approved_hosts'],'policy_status':org['policy_status']}}
            adapter=build_adapter(source);row={'institution':org['slug'],'channel':source['slug'],'checked_at':now().isoformat(),'records':[],'failures':[]}
            try:
                found=list(adapter.discover());row['discovered']=len(found)
                for candidate in found[:args.sample_size]:
                    try:
                        detail=adapter.fetch_detail(candidate);program=adapter.normalize(candidate,detail,[])
                        row['records'].append({'candidate':asdict(candidate),'detail':asdict(detail),'program':program.model_dump(mode='json')})
                    except Exception as error:row['failures'].append(error.record(url=candidate.official_detail_url) if isinstance(error,SourceFailure) else {'kind':type(error).__name__,'message':str(error)[:300]})
            except Exception as error:row['failures'].append(error.record() if isinstance(error,SourceFailure) else {'kind':type(error).__name__,'message':str(error)[:300]})
            row['sample_status']='PARTIAL' if row['failures'] and row['records'] else 'FAILED' if row['failures'] else 'SUCCESS'
            row['coverage']=adapter.pagination.report();results.append(row)
            Path(args.output).write_text(json.dumps({'scope':'BOUNDED_PUBLIC_SOURCE_SAMPLE','sample_limit_per_channel':args.sample_size,'results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            print(json.dumps({'channel':row['channel'],'status':row['sample_status'],'discovered':row.get('discovered'),'parsed':len(row['records']),'failures':row['failures']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
