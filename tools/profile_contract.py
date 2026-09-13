"""Generate the SQL profile contract from the authoritative Python model."""
from radar.models import TeamProfile, PRESETS

def contract():
    schema=TeamProfile.model_json_schema();fields={}
    for key, prop in schema['properties'].items():
        nullable=any(v.get('type')=='null' for v in prop.get('anyOf',[]))
        spec=next((v for v in prop.get('anyOf',[]) if v.get('type')!='null'),prop)
        if '$ref' in spec:spec=schema['$defs'][spec['$ref'].split('/')[-1]]
        result={k:v for k,v in spec.items() if k in ('type','enum','minimum','maximum','format','minItems','maxItems')}
        result['nullable']=nullable
        if 'items' in spec:
            item=spec['items']
            if '$ref' in item:item=schema['$defs'][item['$ref'].split('/')[-1]]
            result['items']={k:v for k,v in item.items() if k in ('type','enum')}
        fields[key]=result
    return {'fields':fields,'defaults':TeamProfile().model_dump(mode='json'),'presets':[p[1] for p in PRESETS]}

if __name__=='__main__':
    import json
    print(json.dumps(contract(),ensure_ascii=False,sort_keys=True))
