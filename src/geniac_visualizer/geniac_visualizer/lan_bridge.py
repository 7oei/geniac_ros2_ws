"""Allowlisted sensor telemetry to LAN. Never forward camera or microphone topics."""
import threading
import rclpy
from rclpy.node import Node
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile,DurabilityPolicy,qos_profile_sensor_data
from std_msgs.msg import String
from std_srvs.srv import Trigger
from sensor_msgs.msg import PointCloud2
from visualization_msgs.msg import MarkerArray
from tf2_msgs.msg import TFMessage
from .local_network import configure_local,LOCAL_DOMAIN

# Full-resolution LiDAR is kept local too; only the preview crosses the LAN.
FORWARDED={'/geniac_detector/tracks':String,'/geniac_detector/markers':MarkerArray,
 '/geniac/behavior':String,'/geniac/scenario/state':String,'/geniac/scenario/tree':String,
 '/geniac/scenario/stock':String,'/geniac/recording/status':String,
 '/geniac/visualization/cloud':PointCloud2,'/tf':TFMessage,'/tf_static':TFMessage}
SERVICES=['/geniac/scenario/start','/geniac/scenario/stop','/geniac/recording/start','/geniac/recording/stop']

def main():
    public_context=Context();rclpy.init(context=public_context,domain_id=105)
    public=Node('geniac_lan_bridge',context=public_context)
    configure_local()
    local_context=Context();rclpy.init(context=local_context,domain_id=LOCAL_DOMAIN)
    local=Node('geniac_local_bridge',context=local_context)
    subscriptions=[];publishers=[];services=[]
    for topic,typ in FORWARDED.items():
        durable=topic in ('/tf_static','/geniac/scenario/state','/geniac/scenario/tree','/geniac/scenario/stock')
        qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL) if durable else qos_profile_sensor_data
        publisher=public.create_publisher(typ,topic,qos if durable or typ is PointCloud2 else 10);publishers.append(publisher)
        subscriptions.append(local.create_subscription(typ,topic,publisher.publish,qos))
    for name in SERVICES:
        client=local.create_client(Trigger,name)
        def forward(request,response,client=client):
            if not client.service_is_ready():response.success=False;response.message='k5 service unavailable';return response
            event=threading.Event();future=client.call_async(request);future.add_done_callback(lambda _:event.set())
            if not event.wait(25):response.success=False;response.message='k5 service timed out';return response
            try:return future.result()
            except Exception:response.success=False;response.message='k5 service failed';return response
        services.append(public.create_service(Trigger,name,forward))
    local_executor=SingleThreadedExecutor(context=local_context);local_executor.add_node(local)
    thread=threading.Thread(target=local_executor.spin,daemon=True);thread.start()
    try:rclpy.spin(public)
    finally:
        local_executor.shutdown();thread.join(timeout=2);local.destroy_node();public.destroy_node()
        for ctx in (local_context,public_context):
            if ctx.ok():rclpy.shutdown(context=ctx)
