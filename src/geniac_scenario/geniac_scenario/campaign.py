"""Sensor-controlled campaign: start after a two-second stop, repeat until escape."""
from geniac_behavior.core import group_response
from .tree import Engine
from .evaluation import Trial


class Campaign:
    def __init__(self,tree,armed=True,sink=None,mode='simulation',volume=30):
        self.core=Engine(tree);self.armed=armed;self.active=False;self.round=0
        self.waiting='stationary_deer';self.cohort=set()
        self.sink=sink;self.mode=mode;self.volume=volume;self.trial=None;self.last_result=None
        self.paused=False;self.pause_elapsed=0.;self.retry_at=0.

    def finish_trial(self,outcome,now):
        if self.trial:
            result=self.trial.finish(outcome,now)
            if result:
                self.last_result=result
                if self.sink:self.sink(result)

    def stop(self,reason='operator_stop'):
        self.paused=False
        self.finish_trial('interrupted',self.trial.last if self.trial else 0)
        self.core.stop(reason);self.active=False;self.armed=False;self.waiting=reason

    def pause(self,reason,now):
        if not self.armed or self.paused or not self.core.running:return False
        self.pause_elapsed=min(max(0.,now-self.core.entered),self.core.tree['nodes'][self.core.node_id]['duration'])
        self.paused=True;self.waiting=reason
        self.retry_at=now+1. if reason.startswith('audio_') else now
        self.core.stop(reason)
        return True

    def tick(self,now,stamp,report,fresh=True,next_tree=None,input_reason='input_stale'):
        if not self.armed:return False
        if not fresh:
            if self.core.running:return self.pause(input_reason,now)
            return False
        targets=report.get('targets',[])
        visible=[t for t in targets if t.get('present') is True and t.get('label') not in ('unknown','escaped')]
        if self.active:self.cohort.update(t['id'] for t in visible)
        if self.paused:
            if report.get('valid') is not True or report.get('epoch')!=self.core.epoch:return False
            self.core.cohort.update(t['id'] for t in visible)
            response=group_response(targets,self.core.cohort)
            if response=='escaped':
                self.core._enter(self.core.tree['nodes'][self.core.node_id]['branches']['escaped'],now,stamp,'escaped')
                self.paused=False;self.active=False;self.waiting='stationary_deer'
                self.finish_trial('escaped',now)
                return True
            if response not in ('no_escape','retreated_nearby') or now<self.retry_at:return False
            self.paused=False;self.core.running=True;self.waiting='playing'
            self.core.entered=now-self.pause_elapsed;self.core.entered_stamp=stamp-self.pause_elapsed
            self.core.reason='resumed'
            # An already completed clip only needs the now-confirmed reaction.
            if self.pause_elapsed>=self.core.tree['nodes'][self.core.node_id]['duration']:
                self.core.tick(now,stamp,report)
            return True
        if self.trial and not self.trial.done:
            escaped=self.trial.observe(now,self.core,targets,
                report.get('valid') is True and (not self.core.running or report.get('epoch')==self.core.epoch))
            if escaped:self.finish_trial('escaped',now)
        if self.core.running:
            previous=dict(self.core.__dict__);previous['transitions']=list(self.core.transitions)
            changed=self.core.tick(now,stamp,report)
            if changed and self.core.reason=='timeout_unknown':
                self.core.__dict__.update(previous)
                return self.pause('input_unknown',now)
            if changed and not self.core.running:
                if self.core.reason=='escaped':
                    self.active=False;self.waiting='stationary_deer'
                # Pending/unknown outcomes remain censored until confirmation or the next trial.
                group=group_response(targets,self.cohort)
                if group in ('no_escape','retreated_nearby'):self.finish_trial('not_escaped',now)
            return changed
        if self.active and group_response(targets,self.cohort)=='escaped':
            self.active=False;self.waiting='stationary_deer';return False
        if self.active:
            if not visible or any(t.get('label') in ('unknown','observing') and t.get('present') is False for t in targets if t['id'] in self.cohort):
                self.waiting='reaction_confirmation';return False
        elif not any(t.get('stationary_seconds',0)>=2. for t in visible):
            self.waiting='stationary_deer';return False
        if not visible:return False
        if self.trial and not self.trial.done:self.finish_trial('unknown',now)
        if next_tree is not None:
            tree=next_tree()
            if tree is None:self.waiting='story_stock';return False
            self.core=Engine(tree)
        if not self.active:self.cohort={t['id'] for t in visible};self.round=0
        labels={t['id']:t['label'] for t in targets}
        self.cohort={key for key in self.cohort if labels.get(key)!='escaped'}
        self.active=True;self.round+=1;self.waiting='playing'
        self.core.start(now,stamp,self.cohort)
        self.trial=Trial(self.core,now,self.mode,self.volume)
        return True
