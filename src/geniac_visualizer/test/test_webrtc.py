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
