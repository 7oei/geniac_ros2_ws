"""Verified speech recordings with persistent least-recently-used selection."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import uuid
from .assets import search,download,verify_candidate,forbidden_material,speech_evidence
from .prepare import credentials,decode
from .billing import guard,BillingRequired,block

QUERIES=('radio speech','walkie talkie voice','radio dispatch','radio communication',
         'radio chatter','military radio voice','police radio voice','radio message',
         'walkie talkie talking','radio response','radio conversation','radio spoken')
BASE_NEED={'kind':'voice','speech_required':True,'description':'Short audible human speech over a communication radio; actual words, not only static or squelch.',
           'queries':['radio speech'],'intensity':1}

def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(path)

def read(root):
    path=Path(root)/'speech_pool.json'
    return json.loads(path.read_text()) if path.exists() else {'version':1,'assets':[],'recent':[],'verified':{}}

def signature(need):return hashlib.sha256(json.dumps(need,sort_keys=True).encode()).hexdigest()

def expand_roles(tree):
    """Give each spoken cue its own material slot, including repeated scene roles."""
    used=set()
    for node in tree['nodes'].values():
        for cue in node.get('cues',[]):
            role=cue['role'];need=tree['needs'][role]
            if not need.get('speech_required'):continue
            if role in used:
                index=2
                while f'{role}_line{index}' in tree['needs']:index+=1
                new=f'{role}_line{index}'
                tree['needs'][new]=copy.deepcopy(need);cue['role']=new
                used.add(new)
            else:used.add(role)
    return tree

def select(root,need,config=None):
    pool=read(root);recent=pool.get('recent',[])
    assets=[a for a in pool['assets'] if Path(a['file']).is_file() and not forbidden_material(a) and speech_evidence(a)]
    # Ten distinct recordings are exhausted before the first one is reused.
    rank={key:i for i,key in enumerate(recent)}
    def speaker(asset):return asset.get('attribution','').split(' — ')[0]
    previous=next((speaker(a) for a in assets if recent and a['id']==recent[-1]),'')
    assets.sort(key=lambda a:(a['id'] in rank,rank.get(a['id'],-1),
                              bool(previous and speaker(a)==previous),a['id']))
    key=signature(need);verified=pool.setdefault('verified',{}).setdefault(key,{})
    for asset in assets:
        proof=verified.get(asset['id'])
        if proof is None and config is not None:
            proof=verify_candidate(need,asset,config) or False
            verified[asset['id']]=proof
        if not proof:continue
        chosen=copy.deepcopy(asset);chosen['verification']=proof
        pool['recent']=[x for x in recent if x!=asset['id']]+[asset['id']]
        save(Path(root)/'speech_pool.json',pool)
        return chosen
    if config is not None and assets:save(Path(root)/'speech_pool.json',pool)
    return None

def build(root,config,count=10):
    guard(config);root=Path(root);pool=read(root)
    seen={a['id'] for a in pool['assets']};hashes={a.get('sha256') for a in pool['assets']}
    target=root/'speech_assets';target.mkdir(parents=True,exist_ok=True)
    for query in QUERIES:
        if len(pool['assets'])>=count:break
        for candidate in search(query,config.get('FREESOUND_API_KEY','')):
            if len(pool['assets'])>=count:break
            if candidate['id'] in seen:continue
            seen.add(candidate['id'])
            if not .5<=float(candidate['duration'])<=8 or forbidden_material(candidate) or not speech_evidence(candidate):continue
            proof=verify_candidate(BASE_NEED,candidate,config)
            if not proof:continue
            file=target/(candidate['id']+'.mp3')
            asset=download(candidate,file) if not file.exists() else dict(candidate,file=str(file))
            samples=decode(file);duration=len(samples)/24000
            digest=hashlib.sha256(samples.tobytes()).hexdigest()
            if duration<.5 or digest in hashes:continue
            asset.update(duration=duration,sha256=digest,verification=proof,selection_basis=proof['method'])
            pool['assets'].append(asset);hashes.add(digest)
            pool.setdefault('verified',{}).setdefault(signature(BASE_NEED),{})[asset['id']]=proof
            save(root/'speech_pool.json',pool)
            print(f"Verified speech recordings: {len(pool['assets'])}/{count} (id={asset['id']})",flush=True)
    return len(pool['assets'])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--env',required=True)
    parser.add_argument('--count',type=int,default=10)
    args=parser.parse_args();config=credentials(args.env);config['_billing_root']=args.root
    try:
        total=build(args.root,config,count=args.count)
        print(f'Speech pool: {total} distinct recordings',flush=True)
        if total<10:raise SystemExit('Fewer than ten verified speech recordings found')
    except BillingRequired as exc:
        block(args.root,exc);raise SystemExit('Additional billing approval required; existing materials retained')

if __name__=='__main__':main()
