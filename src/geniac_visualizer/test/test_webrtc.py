import asyncio
import time
import pytest
pytest.importorskip('aiortc')
from geniac_visualizer.webrtc_server import Audio

def test_audio_frames_are_paced_and_timestamped(monkeypatch):
    class Reader:
        async def readexactly(self,n):return bytes(n)
    class Process:
        returncode=None
        stdout=Reader()
    class Media:start=0.
    async def check():
        a=Audio(Media());a.process=Process()
        first=await a.recv();started=time.monotonic();second=await a.recv()
        assert time.monotonic()-started>=.015
        assert second.pts-first.pts==960
        assert first.sample_rate==48000 and first.samples==960
    asyncio.run(check())


def test_raw_ir_handles_row_padding():
    from types import SimpleNamespace
    from geniac_visualizer.webrtc_server import Media
    async def check():
        m=Media(asyncio.get_running_loop())
        m.raw_video(SimpleNamespace(encoding='mono8',width=2,height=2,step=3,data=bytes([10,20,99,30,40,99])))
        assert m.image.shape==(2,2,3)
        assert m.image[:,:,0].tolist()==[[10,20],[30,40]]
        assert m.image_event.is_set()
    asyncio.run(check())


def test_auto_media_outputs_only_selected_source(monkeypatch):
    from types import SimpleNamespace as NS
    import cv2,numpy as np
    from geniac_visualizer.webrtc_server import AutoMedia
    clock=[0.]
    monkeypatch.setattr('geniac_visualizer.webrtc_server.time.monotonic',lambda:clock[0])
    def rgb(level):return NS(data=cv2.imencode('.jpg',np.full((4,4,3),level,np.uint8))[1].tobytes())
    async def check():
        m=AutoMedia(asyncio.get_running_loop())
        ir=NS(encoding='mono8',width=2,height=2,step=2,data=bytes([80]*4))
        for t in range(4):
            clock[0]=t;m.rgb(rgb(10));m.ir(ir)
        assert m.selected=='ir' and isinstance(m.image,np.ndarray)
        m.rgb(rgb(10))
        assert isinstance(m.image,np.ndarray)
        for t in range(4,10):
            clock[0]=t;m.rgb(rgb(75));m.ir(ir)
        assert m.selected=='rgb' and m.image==rgb(75).data
        previous=m.image;m.rgb(NS(data=b'invalid'))
        assert m.image==previous
    asyncio.run(check())
