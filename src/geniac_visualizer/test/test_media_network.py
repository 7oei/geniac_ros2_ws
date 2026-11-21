from geniac_visualizer.local_network import local_environment
from geniac_visualizer.lan_bridge import FORWARDED,SERVICES

def test_camera_and_audio_never_exported_to_lan():
    assert not any(x.startswith('/camera/') for x in FORWARDED)
    assert '/livox/lidar' not in FORWARDED
    assert '/geniac/visualization/cloud' in FORWARDED
    assert '/geniac/recording/stop' in SERVICES

def test_local_dds_has_only_loopback_peers():
    d=local_environment()
    assert d['ROS_LOCALHOST_ONLY']=='0' and d['ROS_DOMAIN_ID']=='106'
    assert 'name="lo"' in d['CYCLONEDDS_URI'] and '192.168.' not in d['CYCLONEDDS_URI']
