import json
import subprocess
import numpy as np
import pytest
from geniac_visualizer.scenario_audio import mux_audio,audio_info,AudioPending,prune_audio
from geniac_visualizer.screen_video import atomic_json


def run(args):return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout


@pytest.fixture
def media(tmp_path):
    video=tmp_path/'video.mp4';audio=tmp_path/'audio';(audio/'episodes').mkdir(parents=True)
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=black:s=160x120:r=10:d=2','-c:v','libx264','-pix_fmt','yuv420p',str(video)])
    sound=audio/'test.mka'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',
         '-af','adelay=500:all=1','-output_ts_offset','100','-c:a','flac',str(sound)])
    meta=audio_info(sound);assert meta['start']==100 and 1.4<meta['duration']<1.6
    atomic_json(audio/'episodes'/('a'*32+'.json'),{'state':'done','bag':'test','file':sound.name,**meta})
    return tmp_path,video


def decoded(path):
    return np.frombuffer(run(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-f','f32le','-ac','1','-ar','48000','-']),dtype='<f4')


def test_mux_trims_audio_before_first_video_frame(media):
    root,video=media
    result,status=mux_audio(root,{'episode':'a'*32,'created':9999,'sensor_started':100.5,'duration':1.},video,root/'mux.mp4')
    assert status=='recorded_output'
    samples=decoded(result);assert np.std(samples[:9600])>.02
    assert abs(len(samples)/48000-1)<.05


def test_mux_pads_late_audio_without_truncating_video(media):
    root,video=media
    result,status=mux_audio(root,{'episode':'a'*32,'created':99.75,'duration':2.},video,root/'mux.mp4')
    samples=decoded(result)
    assert np.max(np.abs(samples[:24000]))<.001
    assert np.std(samples[48000:57600])>.02
    assert abs(len(samples)/48000-2)<.05


def test_pending_audio_retries_and_missing_audio_is_explicit(media):
    root,video=media;index=root/'audio/episodes'/('a'*32+'.json')
    index.write_text(json.dumps({'state':'recording'}))
    with pytest.raises(AudioPending):mux_audio(root,{'episode':'a'*32},video,root/'mux.mp4')
    index.write_text(json.dumps({'state':'failed'}))
    assert mux_audio(root,{'episode':'a'*32},video,root/'mux.mp4')==(video,'capture_failed')
    assert mux_audio(root,{'episode':'old_recording'},video,root/'mux.mp4')==(video,'unavailable')


def test_audio_cache_removed_with_its_bag(media):
    root,_=media;prune_audio(root,'test')
    assert not (root/'audio/test.mka').exists()
    assert not list((root/'audio/episodes').glob('*.json'))
