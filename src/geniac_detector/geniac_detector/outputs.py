"""Fixed-frame outputs: JSON tracks, dynamic candidate TF and RViz markers."""
import json
from builtin_interfaces.msg import Duration
from geometry_msgs.msg import TransformStamped
from std_msgs.msg import String
from visualization_msgs.msg import MarkerArray, Marker


def make_outputs(header, tracks, previous_marker_ids, lifetime_s):
    markers, transforms, active = MarkerArray(), [], set()
    payload = {'version': 1, 'stamp': header.stamp.sec + header.stamp.nanosec / 1e9,
               'frame_id': header.frame_id, 'tracks': tracks}
    for tr in tracks:
        child, center = tr['child_frame_id'], tr['center']
        tf = TransformStamped(header=header, child_frame_id=child)
        tf.transform.translation.x, tf.transform.translation.y, tf.transform.translation.z = map(float, center)
        tf.transform.rotation.w = 1.0
        transforms.append(tf)
        for text in (False, True):
            m = Marker(header=header, ns='geniac_deer', id=2 * int(tr['track_id']) + int(text))
            active.add(m.id)
            m.action = Marker.ADD
            m.type = Marker.TEXT_VIEW_FACING if text else Marker.CUBE
            m.pose.position.x, m.pose.position.y, m.pose.position.z = map(float, center)
            m.pose.orientation.w = 1.0
            if text:
                m.pose.position.z = float(tr['hi'][2]) + .3
                m.scale.z = .35
                m.text = child + ' score=' + format(tr['score'], '.2f')
            else:
                m.scale.x, m.scale.y, m.scale.z = [max(float(b-a), .02) for a,b in zip(tr['lo'],tr['hi'])]
            m.color.r, m.color.g, m.color.b, m.color.a = .1, .9, .3, 1.0 if text else .3
            ns = int(lifetime_s * 1e9)
            m.lifetime = Duration(sec=ns // 1000000000, nanosec=ns % 1000000000)
            markers.markers.append(m)
    for marker_id in sorted(previous_marker_ids - active):
        markers.markers.append(Marker(header=header, ns='geniac_deer', id=marker_id, action=Marker.DELETE))
    return String(data=json.dumps(payload, allow_nan=False)), transforms, markers, active
