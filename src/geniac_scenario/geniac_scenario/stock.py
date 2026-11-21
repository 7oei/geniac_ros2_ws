"""Background preparation and atomic publication of ready-to-play story stock."""
import argparse
import fcntl
from datetime import datetime
import hashlib
import json
import re
import random
from pathlib import Path
import time
import uuid
import yaml
from .weather import fetch_weather, JST
from .story import attach_events
from .evolving import generate, validate_climax
from .history import History
from .assets import search, download, verify_candidate, forbidden_material, speech_evidence, human_speech_valid, context_compatible, manifest_context_valid, vehicle_door_required
from .prepare import credentials, compile_tree, decode
from .tree import runtime_tree, load_tree, audio_paths
from .billing import guard, BillingRequired, state as billing_state, block as block_billing


class MaterialUnavailable(ValueError):
    def __init__(self,role,need,queries,reason):
        super().__init__(reason+' for '+role)
        self.failure={'role':role,'need':need,'search_queries':queries,'reason':reason}

DEFAULT_STOCK=Path.home()/'.local/share/geniac/story_stock'


def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.name=='status.json':
        with History(path.parent).connect() as c:
            data['latest_sequence']=c.execute('SELECT MAX(sequence) FROM stories WHERE path IS NOT NULL').fetchone()[0]
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(path)


def report_progress(root,**updates):
    path=Path(root)/'status.json'
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):data={}
    if data.get('status')!=updates.get('status',data.get('status')) or 'stage_started' not in data:
        data['stage_started']=time.time()
    data.update(updates);data['updated_at']=time.time()
    atomic_json(path,data)


class Stock:
    def __init__(self,root):self.root=Path(root).expanduser();self.index=0

    def ready(self,date=None,status='ready'):
        date=date or datetime.now(JST).date().isoformat()
        try:
            if (self.root/'history.sqlite3').exists():
                entries=[r['path'] for r in History(self.root).rows(status,date)]
            else:
                data=json.loads((self.root/'ready.json').read_text())
                if data['date']!=date or status!='ready':return []
                entries=data['trees']
        except (OSError,ValueError,KeyError,TypeError):return []
        result=[]
        for entry in entries:
            # One broken record must not hide every healthy story.
            try:
                path=(self.root/entry).resolve()
                if not path.is_relative_to(self.root.resolve()):continue
                tree=runtime_tree(load_tree(path));audio_paths(tree,path.parent,require=True)
                if tree.get('story',{}).get('design_version',0)<3:continue
                validate_climax(tree)
                manifest_path=path.parent.parent/'manifest.yaml'
                if manifest_path.exists():
                    manifest=yaml.safe_load(manifest_path.read_text())
                    if any(forbidden_material(a) for a in manifest['assets'].values()):continue
                    if not human_speech_valid(tree,manifest) or not manifest_context_valid(tree,manifest):continue
                    from .core_cast import validate as validate_core_cast
                    validate_core_cast(tree,manifest)
                weather=tree.get('story',{}).get('weather',{})
                if weather.get('date')!=date:continue
                current=self.root/'weather.json'
                if current.exists():
                    observed=json.loads(current.read_text())
                    if observed.get('date')==date and observed.get('surface')!=weather.get('surface'):continue
                result.append(path)
            except (OSError,ValueError,KeyError,TypeError,yaml.YAMLError):continue
        return result

    def next(self,consume=False):
        # New material first; previously completed, still-valid stories are reserve stock.
        for status in ('ready','used'):
            paths=self.ready(status=status)
            if not paths:continue
            if consume:
                history=History(self.root)
                for path in paths:
                    sid=load_tree(path).get('story',{}).get('id')
                    if sid and history.claim(sid,reuse=status=='used'):return path
            else:
                path=paths[self.index%len(paths)];self.index+=1
                return path
        return None


def search_queries(need,surface):
    original=need.get('queries',[need.get('query','')])
    queries=[]
    if vehicle_door_required(need):
        queries.extend(['car door opening','vehicle door open close','van door opening'])
        original=[q if re.search(r'\b(car|vehicle|van|truck|automobile|taxi|pickup)\b',q,re.I) else 'car '+q for q in original]
    if need.get('speech_required'):
        queries.append('radio voice speech' if 'radio' in ' '.join(original).lower() else 'people talking conversation')
    if need.get('kind')=='footsteps':
        text=' '.join(original).lower()
        gait='running footsteps' if re.search(r'\b(run|running|jog|jogging|sprint|sprinting)\b',text) else ('stealth footsteps' if re.search(r'\b(stealth|sneak|sneaking|creeping|tiptoe)\b',text) else 'footsteps')
        queries.append(gait+' '+{'grass':'grass','snow':'snow','rain':'puddles'}[surface])
    stop=set('a an the and or on in at of to from with without through near away field recording recordings outdoor outdoors forest woods woodland distance distant far close medium soft short brief human moving walking approaching slowing left right nonverbal no speech voice night ambience ambiences near-field clear clearer then slightly into fading receding ground microphone'.split())
    for query in original:
        tokens=[word for word in re.findall(r'[a-z]+',query.lower()) if word not in stop]
        compact=' '.join(tokens)
        if compact:queries.append(compact)
    queries.extend(original)
    return list(dict.fromkeys(q for q in queries if q))[:9]


def fetch_alternative(need,queries,required_duration,cache,token,config,role,exclude=()):
    guard(config)
    seen=set();excluded=set(exclude)
    for query in queries:
        checked_in_query=0
        for item in search(query,config.get('FREESOUND_API_KEY','')):
            if item['id'] in seen or item['id'] in excluded or float(item['duration'])<required_duration:continue
            if need.get('speech_required') and float(item['duration'])>8:continue
            seen.add(item['id']);checked_in_query+=1
            verification=verify_candidate(need,item,config)
            if verification:
                target=cache/(token+'-'+uuid.uuid4().hex[:8]+'.mp3')
                asset=download(item,target)
                samples=decode(target);asset['duration']=len(samples)/24000
                if asset['duration']<required_duration:
                    if checked_in_query>=2:break
                    continue
                asset['sha256']=hashlib.sha256(samples.tobytes()).hexdigest()
                asset['verification']=verification;asset['selection_basis']=verification['method']
                return asset
            if checked_in_query>=2 or len(seen)>=18:break
        if len(seen)>=18:break
    failure=MaterialUnavailable(role,need,queries,'No verified recording')
    failure.failure['rejected_ids']=sorted(seen)
    raise failure


def recover_material(tree,role,queries,required_duration,cache,token,config,root,failure):
    if not config.get('OPENAI_API_KEY'):raise failure
    from .material_recovery import ask,queries_from,local_edit
    need=tree['needs'][role];tried=list(queries);attempts=[]
    payload={'story':tree,'role':role,'failed_queries':tried,'failure':failure.failure}
    for stage in ('queries','scene'):
        report_progress(root,status='acquiring',item=('検索語を変更して再探索：' if stage=='queries' else '該当場面だけを調整：')+role)
        try:
            proposal=ask(stage,payload,config)
            new_queries=queries_from(proposal,tried)
            if not new_queries:raise ValueError('No new search queries')
            candidate_tree=tree if stage=='queries' else local_edit(tree,role,proposal)
            if stage=='scene' and ask('check',{'original':tree,'proposed':candidate_tree,'role':role},config).get('compatible') is not True:
                raise ValueError('Local scene edit conflicts with story')
            candidate_need=candidate_tree['needs'][role]
            tried.extend(new_queries)
            asset=fetch_alternative(candidate_need,new_queries,required_duration,cache,token,config,role,
                                    failure.failure.get('rejected_ids',[]) if stage=='queries' else ())
            if stage=='scene':
                tree['needs'][role]=candidate_need
                for key in proposal.get('scenes',{}):tree['nodes'][key]=candidate_tree['nodes'][key]
            else:
                tree['needs'][role]['queries']=new_queries
                tree['needs'][role]['query']=new_queries[0]
            tree['story'].setdefault('material_recoveries',[]).append({'role':role,'stage':stage,'queries':new_queries,'asset_id':asset['id']})
            tree['story']['sound_plan']=dict(tree['needs'])
            tree['story']['outline']=[{'node':k,'title':v.get('title'),'narrative':v.get('narrative'),'branches':v.get('branches')} for k,v in tree['nodes'].items()]
            return asset
        except ValueError as exc:
            attempts.append({'stage':stage,'reason':str(exc)[:180]})
            payload['failed_queries']=list(tried);payload['previous_attempts']=attempts
    failure.failure.update(search_queries=list(dict.fromkeys(tried)),recovery_attempts=attempts)
    raise failure


def acquire(tree,root,config,refresh=False):
    from .speech_pool import expand_roles
    expand_roles(tree)
    reuse_counts=History(root).reuse_counts()
    rotation_path=Path(root)/'material_rotation.json'
    rotation=json.loads(rotation_path.read_text()) if rotation_path.exists() else {'families':{}}
    cache=Path(root)/'assets';cache.mkdir(parents=True,exist_ok=True);manifest={'assets':{}}
    for role,need in tree['needs'].items():
        if need.get('event')=='exit' and tree['story'].get('arrival',{}).get('travel_mode')=='vehicle':
            need['physical_source']='vehicle_door'
        report_progress(root,status='acquiring',completed=len(manifest['assets']),total=len(tree['needs']),item=need.get('description',role))
        if need.get('speech_required'):
            from .speech_pool import select
            speech=select(root,need,config)
            if speech is not None:
                manifest['assets'][role]=speech
                continue
        queries=search_queries(need,tree['story']['weather']['surface'])
        required_duration=2. if need.get('event')=='transport' else .5
        token=hashlib.sha256(json.dumps([3,need,queries,required_duration],sort_keys=True).encode()).hexdigest()[:16]
        meta=cache/(token+'.json')
        if meta.exists() and (not context_compatible(need,json.loads(meta.read_text())) or forbidden_material(json.loads(meta.read_text())) or (need.get('speech_required') and not speech_evidence(json.loads(meta.read_text())))):
            meta.rename(meta.with_suffix('.rejected.json'))
        asset=None
        if meta.exists():
            asset=json.loads(meta.read_text())
            if not Path(asset['file']).is_file():raise ValueError('Cached recording missing')
            if forbidden_material(asset):raise ValueError('Cached recording is music or a composite gun loop')
            if asset.get('verification',{}).get('policy_version')!=3:raise ValueError('Unverified cached recording')
        family=':'.join((need.get('kind','sound'),need.get('event','general')))
        history=rotation['families'].setdefault(family,{'uses':0,'recent':[]})
        reuse_total=reuse_counts.get(family,0)
        reuse_delta=max(0,reuse_total-history.get('counted_reuses',0))
        since_refresh=history.get('uses_since_refresh',history['uses'])+reuse_delta
        history['uses']+=reuse_delta
        history['counted_reuses']=reuse_total
        renew=refresh or (since_refresh>=5 and random.random()<.7)
        if asset is None or renew:
            exclude=set(history['recent'][-20:]) if renew else set()
            if renew and asset:exclude.add(asset['id'])
            try:
                fresh=fetch_alternative(need,queries,required_duration,cache,token,config,role,exclude)
                if asset and hashlib.sha256(decode(Path(asset['file'])).tobytes()).hexdigest()==fresh['sha256']:
                    raise MaterialUnavailable(role,need,queries,'Duplicate audio under another ID')
                asset=fresh;atomic_json(meta,asset)
                since_refresh=0
                history['last_refresh']='downloaded';history.pop('refresh_error',None)
            except MaterialUnavailable as exc:
                if asset is not None:
                    history['last_refresh']='kept_existing';history['refresh_error']=type(exc).__name__
                else:
                    asset=recover_material(tree,role,queries,required_duration,cache,token,config,root,exc)
                    # A locally revised requirement must not poison the original cache key.
                    need=tree['needs'][role];queries=search_queries(need,tree['story']['weather']['surface'])
                    token=hashlib.sha256(json.dumps([3,need,queries,required_duration],sort_keys=True).encode()).hexdigest()[:16]
                    atomic_json(cache/(token+'.json'),asset);since_refresh=0
            except BillingRequired as exc:
                block_billing(root,exc)
                if asset is None:raise
                history['last_refresh']='billing_blocked'
            except (OSError,ValueError,RuntimeError) as exc:
                if asset is None:raise
                # Diversity is optional; retain the verified usable recording.
                history['last_refresh']='kept_existing';history['refresh_error']=type(exc).__name__
        history['uses']+=1
        history['uses_since_refresh']=since_refresh+1
        history['recent']=(history['recent']+[asset['id']])[-20:]
        atomic_json(rotation_path,rotation)
        asset['duration']=len(decode(Path(asset['file'])))/24000
        if asset['duration']<required_duration:raise MaterialUnavailable(role,need,queries,'Recording too short after silence trimming')
        manifest['assets'][role]=asset
        report_progress(root,status='acquiring',completed=len(manifest['assets']),total=len(tree['needs']),item=need.get('description',role))
    return manifest


def _replenish(root,config,opponent='auto',count=3,weather=None):
    if not 1<=count<=8:raise ValueError('Stock count must be 1..8')
    root=Path(root).expanduser();root.mkdir(parents=True,exist_ok=True)
    history=History(root)
    provided_weather=weather is not None;weather_fetched=False
    if weather is None:
        cached=root/'weather.json'
        if cached.exists() and time.time()-cached.stat().st_mtime<1800:
            weather=json.loads(cached.read_text())
            if weather.get('date')!=datetime.now(JST).date().isoformat():weather=None
        if weather is None:
            weather=fetch_weather();weather_fetched=True;atomic_json(cached,weather)
    history.expire(weather,design_version=3)
    atomic_json(root/'status.json',{'status':'checking','reserve_count':len(Stock(root).ready(weather['date'],status='used')),'ready_count':len(Stock(root).ready(weather['date'])),'target_count':count,'validation_policy':3})
    # In-use stories occupy a slot until an outcome arrives, so replacement sees their evaluation.
    valid_paths={str(p) for p in Stock(root).ready(weather['date'])}
    for row in history.rows('ready',weather['date']):
        if row['path'] not in valid_paths:
            with history.connect() as connection:
                connection.execute("UPDATE stories SET status='quarantined' WHERE id=? AND status='ready'",(row['id'],))
    if billing_state(root).get('blocked'):
        from .offline_stock import replenish_local
        report_progress(root,status='local_composing',target_count=count,item='既存素材のみで構成しています',completed=0,total=0)
        try:
            replenish_local(root,history,weather,count,lambda done,total,title:report_progress(root,status='local_composing',completed=done,total=total,item=title))
        except ValueError:
            paths=Stock(root).ready(weather['date'])
            atomic_json(root/'status.json',{'status':'local_unavailable','reserve_count':len(Stock(root).ready(weather['date'],status='used')),'target_count':count,'ready_count':len(paths),'item':'現在の天気に合う検証済み素材で構成できません。既存の再生候補を保持しています。'})
            return len(paths)
        paths=Stock(root).ready(weather['date'])
        atomic_json(root/'status.json',{'status':'local_ready','reserve_count':len(Stock(root).ready(weather['date'],status='used')),'target_count':count,'ready_count':len(paths)})
        return len(paths)
    rows=history.rows(date=weather['date'])
    occupied=sum(r['status'] in ('ready','in_use','draft') for r in rows)
    drafts=[r for r in rows if r['status']=='draft']
    while occupied<count and not drafts:
        if not provided_weather and not weather_fetched:
            weather=fetch_weather();weather_fetched=True
            atomic_json(root/'weather.json',weather)
            history.expire(weather,design_version=3)
        report_progress(root,status='designing',target_count=count,sequence=history.next_sequence(),completed=0,total=0,item='分岐ツリーを生成・検証しています')
        tree=generate(weather,history.context(),history.next_sequence(),config,artifact=root/'last_design.json',
                      progress=lambda attempt:report_progress(root,status='designing',item=f'ツリー生成・整合性確認（試行 {attempt}/3）'))
        sid=history.draft(tree,weather)
        drafts.append(next(r for r in history.rows('draft',weather['date']) if r['id']==sid))
        occupied+=1
        # Make each new story usable before starting the next design request.
        break
    if drafts:
        row=drafts[0];tree=json.loads(row['tree'])
        try:
            report_progress(root,status='acquiring',target_count=count,sequence=row['sequence'],completed=0,total=len(tree['needs']),item='音源準備')
            manifest=acquire(tree,root,config)
            batch=root/('generated-'+row['id']);batch.mkdir(exist_ok=True)
            (batch/'manifest.yaml').write_text(yaml.safe_dump(manifest,allow_unicode=True))
            tree=attach_events(tree,manifest)
            output=batch/('audio-'+uuid.uuid4().hex)
            report_progress(root,status='compiling',target_count=count,sequence=row['sequence'],completed=0,total=sum(not n.get('terminal') for n in tree['nodes'].values()),item='素材の読み込み')
            path=compile_tree(tree,manifest,root,output,progress=lambda done,total,title:report_progress(root,status='compiling',completed=done,total=total,item=title))
            history.publish(row['id'],path,tree)
        except Exception as exc:
            # Keep local repairs and acquired-role expansion for the next attempt.
            with history.connect() as connection:
                connection.execute("UPDATE stories SET tree=? WHERE id=? AND status='draft'",(json.dumps(tree),row['id']))
            if not isinstance(exc,BillingRequired):
                history.fail_draft(row['id'],failure=exc.failure if isinstance(exc,MaterialUnavailable) else None)
            raise
    paths=Stock(root).ready(weather['date'])
    atomic_json(root/'ready.json',{'date':weather['date'],'weather':weather,'trees':[str(p.relative_to(root.resolve())) for p in paths]})
    atomic_json(root/'status.json',{'status':'ready' if paths else 'preparing','weather':weather,
        'reserve_count':len(Stock(root).ready(weather['date'],status='used')),'ready_count':len(paths),'target_count':count,'poll_seconds':5,'refill':'after outcome; in-use stories occupy a slot',
        'next_sequence':history.next_sequence()})
    return len(paths)


def replenish(root,config,opponent='auto',count=3,weather=None):
    root=Path(root).expanduser();root.mkdir(parents=True,exist_ok=True)
    with (root/'.prepare.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:return
        config=dict(config,_billing_root=str(root))
        try:return _replenish(root,config,opponent,count,weather)
        except BillingRequired as exc:
            block_billing(root,exc)
            return _replenish(root,config,opponent,count,weather)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-dir',default=str(DEFAULT_STOCK));parser.add_argument('--env')
    parser.add_argument('--opponent',default='auto',help='Legacy argument; evolving generation is not restricted to an opponent')
    parser.add_argument('--count',type=int,default=3);parser.add_argument('--watch',action='store_true')
    args=parser.parse_args(argv)
    while True:
        try:
            ready=replenish(args.stock_dir,credentials(args.env),args.opponent,args.count)
            print('Story stock checked: '+str(ready)+' ready',flush=True)
            delay=5
            if not args.watch and ready is not None and ready<args.count:
                occupied=sum(r['status'] in ('ready','in_use') for r in History(args.stock_dir).rows(date=datetime.now(JST).date().isoformat()))
                if occupied<args.count:
                    current=json.loads((Path(args.stock_dir)/'status.json').read_text())
                    if current.get('status')=='local_unavailable':return
                    continue
        except Exception as exc:
            # Remote payloads and credential strings must never enter status/logs.
            available=Stock(args.stock_dir)
            ready_count=len(available.ready());reserve_count=len(available.ready(status='used'))
            atomic_json(Path(args.stock_dir)/'status.json',{'status':'refill_failed' if ready_count+reserve_count else 'preparation_failed',
                'error_type':type(exc).__name__,'ready_count':ready_count,'reserve_count':reserve_count,'retry_seconds':0})
            print('Story stock preparation failed ('+type(exc).__name__+'); existing stock retained',flush=True)
            if isinstance(exc,ValueError):print(str(exc)[:200],flush=True)
            delay=0  # Retry immediately as requested; no fixed failure cooldown.
            if not args.watch:raise SystemExit(1)
        if not args.watch:return
        time.sleep(delay)


if __name__=='__main__':main()
