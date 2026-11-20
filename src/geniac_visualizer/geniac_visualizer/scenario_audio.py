"""Capture k5 playback monitor, keep wall-clock timestamps and mux matching episodes."""
import json
import os
import re
import signal
import subprocess
from pathlib import Path
from .screen_video import atomic_json

EPISODE=re.compile(r'[a-f0-9]{32}')


def audio_info(path):
    r=subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_entries',
                      'stream=codec_name:format=start_time,duration','-of','json',str(path)],
                     check=True,capture_output=True,timeout=15)
    info=json.loads(r.stdout)
    if not info.get('streams'):raise ValueError('No captured audio')
    start=float(info['format']['start_time']);end=float(info['format']['duration'])
    if start<=0 or end<=start:raise ValueError('Invalid captured audio timestamps')
    return {'start':start,'duration':end-start}


class PlaybackCapture:
    def __init__(self,root,source=None):
        self.source=source
        self.root=Path(root)/'audio';self.process=None;self.log=None;self.output=None;self.episodes=set();self.error='';self.bag=''
    def start(self,bag):
        self.root.mkdir(parents=True,exist_ok=True);(self.root/'episodes').mkdir(exist_ok=True)
        self.bag=bag;self.output=self.root/(bag+'.mka');self.episodes=set();self.error=''
        try:
            sink=self.source or (subprocess.check_output(['pactl','get-default-sink'],timeout=5,text=True).strip()+'.monitor')
            if not sink or '\n' in sink:raise ValueError('No playback sink')
            self.log=(self.root/(bag+'.log')).open('wb')
            self.process=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',
                '-copyts','-f','pulse','-wallclock','1','-sample_rate','48000','-channels','2',
                '-analyzeduration','0','-probesize','32','-i',sink,'-c:a','flac',
                '-flush_packets','1',str(self.output)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=self.log)
        except Exception as exc:self.error=type(exc).__name__
    def bind(self,episode):
        if not EPISODE.fullmatch(episode) or episode in self.episodes:return
        self.episodes.add(episode)
        atomic_json(self.root/'episodes'/(episode+'.json'),{'bag':self.bag,'state':'recording','file':self.output.name,'pid':self.process.pid if self.process else 0})
    def stop(self,bag_directory):
        try:
            if self.process and self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
                try:self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait();raise RuntimeError('Audio stop timed out')
            info=audio_info(self.output)
            state={'bag':self.bag,'state':'done','file':self.output.name,**info}
            # Include the captured output as a sidecar in the same compressed ROSBAG archive.
            target=Path(bag_directory)/'scenario_audio.mka'
            if target.parent.is_dir() and not target.exists():os.link(self.output,target)
            if target.parent.is_dir():atomic_json(target.parent/'scenario_audio.json',state)
        except Exception as exc:
            self.error=type(exc).__name__;state={'bag':self.bag,'state':'failed','error':self.error}
        finally:
            if self.log:self.log.close();self.log=None
            self.process=None
        for episode in self.episodes:atomic_json(self.root/'episodes'/(episode+'.json'),state)
        self.output=None


class AudioPending(RuntimeError):pass


def mux_audio(root,data,video,output):
    episode=data.get('episode','')
    if not EPISODE.fullmatch(episode):return video,'unavailable'
    directory=Path(root)/'audio';index=directory/'episodes'/(episode+'.json')
    if not index.is_file():return video,'unavailable'
    if index.is_symlink():raise ValueError('Invalid audio index')
    meta=json.loads(index.read_text())
    if meta['state']=='recording':
        if 'pid' not in meta:raise AudioPending('Waiting for scenario audio to finish')
        filename=meta.get('file','')
        if Path(filename).name!=filename or not filename.endswith('.mka'):raise ValueError('Invalid audio filename')
        try:alive=str(directory/filename).encode() in Path('/proc/'+str(int(meta['pid']))+'/cmdline').read_bytes().split(b'\0')
        except (OSError,ValueError):alive=False
        if alive:raise AudioPending('Waiting for scenario audio to finish')
        try:meta.update(state='done',**audio_info(directory/filename))
        except Exception:meta['state']='failed'
        atomic_json(index,meta)
    if meta['state']!='done':return video,'capture_failed'
    filename=meta['file']
    if Path(filename).name!=filename or not filename.endswith('.mka'):raise ValueError('Invalid audio filename')
    audio=directory/filename
    if audio.is_symlink() or not audio.is_file():return video,'unavailable'
    start=float(data.get('sensor_started',data['created']));offset=start-float(meta['start'])
    if abs(offset)>86400:return video,'clock_mismatch'
    filters='asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0'
    if offset<0:filters+=f',adelay={round(-offset*1000)}:all=1'
    filters+=',apad'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(video),
                    '-ss',str(max(0,offset)),'-i',str(audio),'-map','0:v:0','-map','1:a:0',
                    '-c:v','copy','-af',filters,'-c:a','aac','-b:a','192k',
                    '-t',str(float(data['duration'])),'-movflags','+faststart',str(output)],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=300)
    return output,'recorded_output'


def prune_audio(root,bag):
    directory=Path(root)/'audio'
    for index in (directory/'episodes').glob('*.json'):
        if index.is_symlink():continue
        try:
            if json.loads(index.read_text()).get('bag')==bag:index.unlink()
        except (ValueError,OSError):continue
    for extension in ('.mka','.log'):
        path=directory/(bag+extension)
        if path.is_file() and not path.is_symlink():path.unlink()
