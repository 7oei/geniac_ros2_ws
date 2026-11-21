import base64,json
import pytest
from geniac_visualizer.microphone import CHUNK,decode_packet
from geniac_visualizer.scenario_audio import PlaybackCapture
from geniac_visualizer.recording import TOPICS

def packet(**changes):
    d=dict(stamp=100,rate=16000,channels=1,format='s16le',pcm=base64.b64encode(bytes(CHUNK)).decode());d.update(changes)
    return json.dumps(d)

def test_pcm_transport_validates_format_length_and_age():
    assert decode_packet(packet(),100)==bytes(CHUNK)
    for text in [packet(rate=48000),packet(channels=2),packet(pcm='bad!'),packet(pcm=''),packet(stamp=90)]:
        with pytest.raises(ValueError):decode_packet(text,100)

def test_microphone_capture_and_bag_topic(tmp_path,monkeypatch):
    monkeypatch.setenv('GENIAC_RECORDING_AUDIO_SOURCE','geniac_microphone')
    assert PlaybackCapture(tmp_path).source=='geniac_microphone'
    assert PlaybackCapture(tmp_path,source='test.monitor').source=='test.monitor'
    assert '/camera/audio/pcm' in TOPICS
