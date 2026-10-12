#!/usr/bin/env python3
"""Replace inherited header/search artwork and optionally remove inherited previews on a CPP draft.

cpm appstore page-artwork --spec artwork.json --out report.json [--commit]
Spec: appId, versionId, localeId, sourceLocaleId, creatives [{placementType,file}],
removeInheritedPreviews (bool). Draft only; no submission or source-listing edits.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request

CREATIVES = {'PRODUCT_PAGE_HEADER_ASSET': (3840, 1646), 'APP_STORE_SEARCH_RESULTS_ASSET': (3840, 2560)}

def rel(kind, ident):
    return {'data': {'type': kind, 'id': ident}}

def fingerprint(p):
    r=p.get('relationships', {})
    return (p['attributes']['placementType'],p['attributes']['placementGroup'],
            (r.get('image', {}).get('data') or {}).get('id'),
            (r.get('video', {}).get('data') or {}).get('id'))

def inherited(p, source):
    return p['id'] not in {s['id'] for s in source} and fingerprint(p) in {fingerprint(s) for s in source}

def placements(asc, kind, lid):
    return asc.get_all(f'/v1/{kind}/{lid}/placements?limit=200&include=image,video&sort=placementGroupPosition')

def draft(asc, vid):
    if asc.get(f'/v1/appCustomProductPageVersions/{vid}')['data']['attributes']['state'] != 'PREPARE_FOR_SUBMISSION':
        raise ValueError('Only a custom page draft can be modified.')

def upload(asc, app_id, f, ref):
    images=asc.get_all(f'/v1/appAssetLibraries/{app_id}/images?filter[referenceName]={ref}&limit=200')
    if len(images)>1: raise ValueError('Duplicate named library assets.')
    if images:
        asset=images[0]; a=asset['attributes']
        if a['fileName']!=f.name or a['fileSize']!=f.stat().st_size or a['category']!='CREATIVE_ASSETS':
            raise ValueError('Existing library asset differs from the file.')
        if a['state']=='AWAITING_UPLOAD': raise ValueError('Interrupted library upload requires inspection.')
    else:
        data=f.read_bytes()
        asset=asc.call('POST','/v1/appAssetLibraryImages',{'data':{'type':'appAssetLibraryImages',
            'attributes':{'category':'CREATIVE_ASSETS','fileName':f.name,'fileSize':len(data),'referenceName':ref},
            'relationships':{'assetLibrary':rel('appAssetLibraries',app_id)}}})['data']
        for op in asset['attributes']['uploadOperations']:
            req=urllib.request.Request(op['url'],data=data[op['offset']:op['offset']+op['length']],method=op['method'],
                headers={h['name']:h['value'] for h in op.get('requestHeaders',[])})
            with urllib.request.urlopen(req,context=asc._context,timeout=120) as response: response.read()
        asc.call('PATCH','/v1/appAssetLibraryImages/'+asset['id'],{'data':{'type':'appAssetLibraryImages','id':asset['id'],'attributes':{'uploaded':True}}})
    for _ in range(15):
        asset=asc.get('/v1/appAssetLibraryImages/'+asset['id'])['data'];a=asset['attributes']
        if a['state'] in {'COMPLETE','PREPARE_FOR_SUBMISSION','READY_FOR_REVIEW','APPROVED','ACCEPTED'}: return asset
        if a['state'] in {'FAILED','REJECTED','ARCHIVED'}: raise ValueError(f'Image processing failed: {a}')
        time.sleep(3)
    raise ValueError(f'Image is still processing ({a["state"]}, {asset["id"]}); rerun to resume.')

def create_placement(asc,lid,ptype,image_id,group='DEFAULT_PROFILE'):
    return asc.call('POST','/v1/appAssetLibraryPlacements',{'data':{'type':'appAssetLibraryPlacements',
        'attributes':{'placementType':ptype,'placementGroup':group},
        'relationships':{'image':rel('appAssetLibraryImages',image_id),
          'appCustomProductPageLocalization':rel('appCustomProductPageLocalizations',lid)}}})['data']

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',required=True);parser.add_argument('--out',required=True);parser.add_argument('--commit',action='store_true')
    args=parser.parse_args(argv); path=Path(args.spec).resolve();spec=json.loads(path.read_text())
    from _asc import ASC
    from screenshots import png_size
    asc=ASC();app_id=spec['appId'];lid=spec['localeId'];vid=spec['versionId'];source_lid=spec['sourceLocaleId']
    draft(asc,vid)
    locs=asc.get_all(f'/v1/appCustomProductPageVersions/{vid}/appCustomProductPageLocalizations?limit=50')
    if lid not in {l['id'] for l in locs}: raise ValueError('Locale does not belong to target draft.')
    source=placements(asc,'appStoreVersionLocalizations',source_lid)
    current=placements(asc,'appCustomProductPageLocalizations',lid)
    report={'versionId':vid,'localeId':lid,'submitted':False,'sourceBefore':source,'before':current,'creatives':[],'removedPreviews':[]}
    assets=[]
    for item in spec['creatives']:
        f=(path.parent/item['file']).resolve();kind=item['placementType']
        if kind not in CREATIVES or png_size(f)!=CREATIVES[kind]: raise ValueError('Invalid creative placement or dimensions.')
        ref='cpm-'+hashlib.sha256(f.read_bytes()).hexdigest()
        matches=[p for p in current if p['attributes']['placementType']==kind]
        for p in matches:
            if inherited(p,source): continue
            ident=(p['relationships'].get('image',{}).get('data') or {}).get('id')
            remote=asc.get('/v1/appAssetLibraryImages/'+ident)['data'] if ident else None
            if not remote or remote['attributes'].get('referenceName')!=ref: raise ValueError('Unknown custom creative; refusing overwrite.')
        assets.append((kind,f,ref,matches));print(f'{kind}: {f.name}',flush=True)
    previews=[p for p in current if p['attributes']['placementType']=='APP_PREVIEW'] if spec.get('removeInheritedPreviews') else []
    if any(not inherited(p,source) for p in previews): raise ValueError('A preview is not a proven inherited copy.')
    print(f'Remove {len(previews)} inherited preview placements from the draft only.',flush=True)
    if not args.commit: print('DRY RUN. No assets changed.');return
    out=Path(args.out)
    def save(): out.write_text(json.dumps(report,indent=2)+'\n')
    save()
    for kind,f,ref,matches in assets:
        asset=upload(asc,app_id,f,ref);draft(asc,vid)
        current=placements(asc,'appCustomProductPageLocalizations',lid)
        active=[p for p in current if p['attributes']['placementType']==kind]
        if {p['id'] for p in active}!={p['id'] for p in matches}: raise ValueError('Concurrent artwork change.')
        same=[p for p in active if (p['relationships'].get('image',{}).get('data') or {}).get('id')==asset['id']]
        if same: placed=same[0]
        else:
            for p in active: asc.call('DELETE','/v1/appAssetLibraryPlacements/'+p['id'])
            try: placed=create_placement(asc,lid,kind,asset['id'])
            except Exception:
                for p in active:
                    create_placement(asc,lid,kind,p['relationships']['image']['data']['id'],p['attributes']['placementGroup'])
                raise
        report['creatives'].append({'placementType':kind,'placementId':placed['id'],'imageId':asset['id'],
            'file':str(f),'sha256':ref[4:],'asset':asset['attributes']});save()
        print(f'Placed {kind}: {asset["id"]}',flush=True)
    for p in previews:
        draft(asc,vid)
        asc.call('DELETE','/v1/appAssetLibraryPlacements/'+p['id']);report['removedPreviews'].append(p['id']);save()
    after=placements(asc,'appCustomProductPageLocalizations',lid)
    for item in report['creatives']:
        matches=[p for p in after if p['attributes']['placementType']==item['placementType']]
        if len(matches)!=1 or matches[0]['relationships']['image']['data']['id']!=item['imageId']: raise ValueError('Placement verification failed.')
    if spec.get('removeInheritedPreviews') and any(p['attributes']['placementType']=='APP_PREVIEW' for p in after): raise ValueError('Preview remains.')
    latest_source=placements(asc,'appStoreVersionLocalizations',source_lid)
    if [(p['id'],fingerprint(p)) for p in source]!=[(p['id'],fingerprint(p)) for p in latest_source]: raise ValueError('Source listing changed during operation.')
    draft(asc,vid);report.update(after=after,sourceUnchanged=True,verified=True);save()
    print('Verified custom artwork, preview removal and unchanged live placements.',flush=True)

if __name__=='__main__':main()
