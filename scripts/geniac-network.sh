#!/bin/bash
# Source on either host; pins DDS to the route to the peer, including Wi-Fi.
GENIAC_PEER_IP=${GENIAC_PEER_IP:-192.168.1.64}
GENIAC_INTERFACE=${GENIAC_INTERFACE:-$(ip -o route get "$GENIAC_PEER_IP" | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1);exit}}')}
if [[ ! "$GENIAC_PEER_IP" =~ ^[0-9.]+$ || ! "$GENIAC_INTERFACE" =~ ^[a-zA-Z0-9_.:-]+$ ]]; then
    echo 'Invalid GENIAC_PEER_IP / GENIAC_INTERFACE' >&2
    return 1 2>/dev/null || exit 1
fi
export ROS_DOMAIN_ID=${GENIAC_DOMAIN_ID:-105} ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"$GENIAC_INTERFACE\"/></Interfaces></General><Discovery><Peers><Peer Address=\"$GENIAC_PEER_IP\"/></Peers><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>100</MaxAutoParticipantIndex></Discovery></Domain></CycloneDDS>"
