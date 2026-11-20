"""Explicit LLM output shape, including physical arrival and per-scene continuity."""
def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def array(items,minimum=0,maximum=16):return {'type':'array','items':items,'minItems':minimum,'maxItems':maximum}
def enum(*values):return {'type':'string','enum':list(values)}
text={'type':'string'}
number={'type':'number'}
arrival=obj({'actor':text,'actor_kind':enum('human','animal','machine','other'),'origin':text,'destination':text,
             'travel_mode':enum('vehicle','walking','flying','swimming','other'),'travel_reason':text,'purpose':text,
             'steps':array(text,3,8),'assumptions':array(text,1,8)})
SOUND_IDS=tuple(f'sound_{i:02d}' for i in range(1,13))
sound_id=dict(enum(*SOUND_IDS),description='Audio material ID from needs[].id. Never a person or cast role.')
need=obj({'speech_required':{'type':'boolean'},'id':sound_id,'description':text,'kind':enum('ambience','footsteps','voice','mechanical','impulse'),
          'intensity':{'type':'integer','enum':[0,1,2,3]},'queries':array(text,1,3),
          'event':enum('transport','stop','exit','movement','action','ambience','attack')})
cue=obj({'sound_id':sound_id,'start':number,'duration':number,'gain_db':number})
scene=obj({'id':text,'terminal':{'type':'boolean','enum':[False]},'title':text,'narrative':text,
           'stage':enum('transport','arrival','approach','interaction','withdrawal'),
           'location':text,'action':text,'cause':text,'duration':number,'min_dwell':number,'level':{'type':'integer','enum':[0,1,2,3]},
           'audio':{'type':'null'},'cues':array(cue,1,12),
           'branches':obj({key:text for key in ('escaped','retreated_nearby','no_escape','unknown')})})
terminal=obj({'id':text,'terminal':{'type':'boolean','enum':[True]},'title':text})
SCHEMA=obj({'version':{'type':'integer','enum':[1]},'root':text,
            'story':obj({'title':text,'premise':text,'direction':text,'change':text,'arrival':arrival,'variation':obj({
                'actor_count':{'type':'integer','minimum':1,'maximum':6},
                'roles':array(text,1,6),
                'approach':enum('together','split','sequential','stationary_support'),
                'dialogue':enum('none','call','conversation','radio_exchange'),
                'movement':enum('walking','running','stealth','mixed','none'),'vehicle':text,'weapon':text,'sound_arrangement':text})}),
            'needs':array(need,1,12),'nodes':array({'anyOf':[scene,terminal]},2,16)})
