"""Sensor ROS domain is loopback-only, independent of LAN DDS settings."""
import os
LOCAL_DOMAIN=106
LOCAL_XML='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><Peers><Peer Address="127.0.0.1"/></Peers><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>100</MaxAutoParticipantIndex></Discovery></Domain></CycloneDDS>'
def local_environment():
    return dict(ROS_DOMAIN_ID=str(LOCAL_DOMAIN),ROS_LOCALHOST_ONLY='0',RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',CYCLONEDDS_URI=LOCAL_XML)
def configure_local():os.environ.update(local_environment())
