"""Durable generation queue and observed outcomes, separate from simulated trials."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid


class History:
    def __init__(self,root):
        self.root=Path(root).expanduser();self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/'history.sqlite3'
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS stories(
              id TEXT PRIMARY KEY, sequence INTEGER UNIQUE, date TEXT, surface TEXT,
              status TEXT, tree TEXT, path TEXT, created REAL, claimed REAL);
            CREATE TABLE IF NOT EXISTS playback_starts(
              trial_id TEXT PRIMARY KEY, story_id TEXT, reused INTEGER, families TEXT);
            CREATE TABLE IF NOT EXISTS outcomes(
              trial_id TEXT PRIMARY KEY, story_id TEXT, mode TEXT, created REAL, result TEXT);
            ''')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=5);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def draft(self,tree,weather):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            seq=c.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM stories').fetchone()[0]
            sid=uuid.uuid4().hex
            tree['story'].update(id=sid,sequence=seq)
            c.execute('INSERT INTO stories VALUES(?,?,?,?,?,?,?,?,?)',
                (sid,seq,weather['date'],weather['surface'],'draft',json.dumps(tree),None,time.time(),None))
        return sid

    def fail_draft(self,sid,failure=None):
        with self.connect() as c:
            row=c.execute("SELECT tree FROM stories WHERE id=? AND status='draft'",(sid,)).fetchone()
            if row:
                tree=json.loads(row[0]);story=tree['story']
                story['preparation_failures']=story.get('preparation_failures',0)+1
                if failure:
                    story['material_failure']=dict(failure,at=time.time())
                status='unrealizable' if failure or story['preparation_failures']>=3 else 'draft'
                c.execute('UPDATE stories SET tree=?,status=? WHERE id=?',(json.dumps(tree),status,sid))

    def next_sequence(self):
        with self.connect() as c:return c.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM stories').fetchone()[0]

    def rows(self,status=None,date=None):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM stories WHERE (? IS NULL OR status=?) AND (? IS NULL OR date=?) ORDER BY sequence',
                (status,status,date,date))]

    def publish(self,sid,path,tree):
        with self.connect() as c:c.execute('UPDATE stories SET status=?,path=?,tree=? WHERE id=? AND status=?',
            ('ready',str(Path(path).resolve()),json.dumps(tree),sid,'draft'))

    def claim(self,sid,reuse=False):
        with self.connect() as c:
            result=c.execute("UPDATE stories SET status='in_use',claimed=? WHERE id=? AND status=?",(time.time(),sid,'used' if reuse else 'ready'))
            if result.rowcount==1 and reuse:
                self._playback(c,sid,uuid.uuid4().hex,True)
            return result.rowcount==1

    def _playback(self,c,sid,trial_id,reused=None):
        row=c.execute('SELECT status,tree FROM stories WHERE id=?',(sid,)).fetchone()
        if row is None:return
        if reused is None:
            reused=row['status']=='used' or c.execute('SELECT 1 FROM playback_starts WHERE story_id=? LIMIT 1',(sid,)).fetchone() is not None
        tree=json.loads(row['tree'])
        roles={cue['role'] for node in tree.get('nodes',{}).values() for cue in node.get('cues',[])}
        families=sorted({':'.join((n.get('kind','sound'),n.get('event','general'))) for role,n in tree.get('needs',{}).items() if role in roles})
        c.execute('INSERT OR IGNORE INTO playback_starts VALUES(?,?,?,?)',(trial_id,sid,int(reused),json.dumps(families)))

    def begin_playback(self,sid,trial_id):
        """Count a preview/test restart once, never individual scene/attack loops."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._playback(c,sid,trial_id)

    def reuse_counts(self):
        counts={}
        with self.connect() as c:
            for row in c.execute('SELECT families FROM playback_starts WHERE reused=1'):
                for family in json.loads(row[0]):counts[family]=counts.get(family,0)+1
        return counts

    def consume_manual(self,sid):
        """Release a previewed ready slot without fabricating a field outcome."""
        with self.connect() as c:
            result=c.execute("UPDATE stories SET status='used' WHERE id=? AND status='ready'",(sid,))
            return result.rowcount==1

    def expire(self,weather,design_version=None):
        with self.connect() as c:
            if design_version is not None:
                c.execute("UPDATE stories SET status='obsolete' WHERE status IN ('draft','ready') AND COALESCE(json_extract(tree,'$.story.design_version'),1)<?",(design_version,))
            c.execute("UPDATE stories SET status='obsolete' WHERE status IN ('draft','ready') AND (date!=? OR surface!=?)",(weather['date'],weather['surface']))
            # Interrupted processes must not hold stock capacity forever or silently recycle a story.
            c.execute("UPDATE stories SET status='interrupted' WHERE status='in_use' AND claimed<?",(time.time()-600,))

    def record(self,result):
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO outcomes VALUES(?,?,?,?,?)',(result['trial_id'],result['story_id'],result['mode'],time.time(),json.dumps(result)))
            if result['mode']=='field':
                c.execute("UPDATE stories SET status='used' WHERE id=? AND status='in_use'",(result['story_id'],))

    def context(self):
        with self.connect() as c:
            eligible="mode='field' AND json_extract(result,'$.outcome') IN ('escaped','not_escaped')"
            rows=c.execute('SELECT result FROM outcomes WHERE '+eligible+' ORDER BY created DESC LIMIT 10').fetchall()
            champions=c.execute("SELECT result FROM outcomes WHERE mode='field' AND json_extract(result,'$.outcome')='escaped' ORDER BY CAST(json_extract(result,'$.score') AS REAL) DESC, created ASC LIMIT 5").fetchall()
            provisional=c.execute("SELECT result FROM outcomes WHERE mode IN ('simulation','manual') AND story_id IN (SELECT id FROM stories WHERE status IN ('ready','used','in_use')) AND json_extract(result,'$.outcome')='escaped' ORDER BY CAST(json_extract(result,'$.score') AS REAL) DESC, created ASC LIMIT 5").fetchall()
            baseline=c.execute("SELECT tree FROM stories WHERE status IN ('ready','used','in_use') AND COALESCE(json_extract(tree,'$.story.strategy'),'seed')!='explore' ORDER BY sequence LIMIT 1").fetchone()
            count=c.execute('SELECT COUNT(*) FROM outcomes WHERE '+eligible).fetchone()[0]
            failures=c.execute("SELECT id,tree FROM stories WHERE json_extract(tree,'$.story.material_failure.at')>? ORDER BY sequence DESC LIMIT 10",(time.time()-86400,)).fetchall()
            recent_stories=c.execute('SELECT tree FROM stories ORDER BY sequence DESC LIMIT 8').fetchall()
            from .exploration import history_summary
            exploration_counts=history_summary(json.loads(r[0]) for r in c.execute('SELECT tree FROM stories'))
        with self.connect() as c:
            sources={r['id']:json.loads(r['tree']) for r in c.execute("SELECT id,tree FROM stories WHERE status IN ('ready','used','in_use') ORDER BY sequence DESC LIMIT 20")}
            for result in champions+rows+provisional:
                sid=json.loads(result[0]).get('story_id')
                row=c.execute("SELECT tree FROM stories WHERE id=? AND status IN ('ready','used','in_use')",(sid,)).fetchone()
                if row and sid not in sources:sources[sid]=json.loads(row[0])
            if baseline:
                base=json.loads(baseline[0]);sources.setdefault(base['story']['id'],base)
        return {'provisional_best':[json.loads(r[0]) for r in provisional],
                'baseline_concept':json.loads(baseline[0])['story'] if baseline else None,
                'exploration_counts':exploration_counts,'source_designs':sources,'best':[json.loads(r[0]) for r in champions],'recent':[json.loads(r[0]) for r in rows],
                'recent_concepts':[json.loads(r[0]).get('story',{}) for r in recent_stories],
                'material_failures':[dict(json.loads(r['tree'])['story']['material_failure'],story_id=r['id']) for r in failures],
                'field_trials':count,
                'note':'Observed outcomes, not proof of causality. Simulations and interrupted/unknown trials excluded.'}
