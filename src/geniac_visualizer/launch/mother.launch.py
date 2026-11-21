from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('cloud_topic',default_value='/geniac/visualization/cloud'),
        DeclareLaunchArgument('use_sim_time',default_value='false'),
        DeclareLaunchArgument('webrtc_enabled',default_value='false'),
        DeclareLaunchArgument('screen_record',default_value='true'),
        Node(prefix=str(Path.home()/'geniac_ros2_ws/.venv-media/bin/python3'),respawn=True,respawn_delay=3.,package='geniac_visualizer',executable='dashboard',output='screen',parameters=[{
            'cloud_topic':LaunchConfiguration('cloud_topic'),
            'webrtc_enabled':ParameterValue(LaunchConfiguration('webrtc_enabled'),value_type=bool),
            'screen_record':ParameterValue(LaunchConfiguration('screen_record'),value_type=bool),
            'use_sim_time':ParameterValue(LaunchConfiguration('use_sim_time'),value_type=bool)}]),
    ])
