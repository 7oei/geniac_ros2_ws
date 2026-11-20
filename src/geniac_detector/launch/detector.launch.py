from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_config = PathJoinSubstitution([FindPackageShare('geniac_detector'), 'config', 'detector.yaml'])
    return LaunchDescription([
        DeclareLaunchArgument('config', default_value=default_config),
        DeclareLaunchArgument('input_topic', default_value='/livox/lidar'),
        DeclareLaunchArgument('lidar_frame', default_value='livox_frame'),
        DeclareLaunchArgument('tf_prefix', default_value='deer_'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        Node(package='geniac_detector', executable='detector', name='geniac_detector', output='screen',
             parameters=[LaunchConfiguration('config'), {
                 'input_topic': LaunchConfiguration('input_topic'),
                 'expected_frame': LaunchConfiguration('lidar_frame'),
                 'tf_prefix': LaunchConfiguration('tf_prefix'),
                 'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
             }]),
    ])
