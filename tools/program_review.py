"""Export source evidence or apply an explicit reviewed decision using worker credentials."""
import argparse
import json
from pathlib import Path
from radar.database import Database
from radar.adapters.base import AcquiredDetail
from radar.program_review import source_packet,evidence_input_hash,apply_review,revoke_review


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    export=commands.add_parser('export');export.add_argument('--program-id',required=True);export.add_argument('--output',required=True)
    apply=commands.add_parser('apply');apply.add_argument('--file',required=True)
    revoke=commands.add_parser('revoke');revoke.add_argument('--review-id',required=True)
    revoke.add_argument('--expected-version-id',required=True);revoke.add_argument('--note',required=True)
    args=parser.parse_args();db=Database()
    if args.command=='export':
        version,snapshot,docs=source_packet(db,args.program_id)
        detail=AcquiredDetail(snapshot['official_detail_url'],version['raw_text'],version['normalized']['title'])
        output={'program_id':args.program_id,'expected_version_id':str(version['id']),
                'source_id':str(snapshot['source_id']),'official_url':detail.url,'detail_text':detail.text,
                'primary_input_hash':evidence_input_hash(snapshot['source_id'],detail,docs,snapshot['raw_metadata']),
                'documents':docs,'current_program':version['normalized']}
        Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print('Source packet exported. This is not an approved decision.')
        return 0
    if args.command=='revoke':result=revoke_review(db,args.review_id,args.expected_version_id,args.note)
    else:
        data=json.loads(Path(args.file).read_text(encoding='utf-8'))
        result=apply_review(db,data['program_id'],data['expected_version_id'],data['decision'])
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status']=='SUCCESS' else 1


if __name__=='__main__':raise SystemExit(main())
