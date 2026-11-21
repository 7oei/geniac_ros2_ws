"""Run on this development PC with recorded clouds, later on k5 with HAP."""
from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    share=lambda p,f:PathJoinSubstitution([FindPackageShare(p),'config',f])
    sim={'use_sim_time':ParameterValue(LaunchConfiguration('use_sim_time'),value_type=bool)}
    return LaunchDescription([
        DeclareLaunchArgument('input_topic',default_value='/livox/lidar'),
        DeclareLaunchArgument('use_sim_time',default_value='false'),
        DeclareLaunchArgument('dry_run',default_value='true'),
        DeclareLaunchArgument('auto_arm',default_value='true'),
        DeclareLaunchArgument('stock_enabled',default_value='true'),
        DeclareLaunchArgument('stock_dir',default_value=str(Path.home()/'.local/share/geniac/story_stock')),
        DeclareLaunchArgument('opponent',default_value='auto'),
        DeclareLaunchArgument('tree_path',default_value=share('geniac_scenario','story_tree.yaml')),
        DeclareLaunchArgument('detector_config',default_value=share('geniac_detector','detector.yaml')),
        DeclareLaunchArgument('behavior_config',default_value=share('geniac_behavior','behavior.yaml')),
        DeclareLaunchArgument('auto_record',default_value='true'),
        DeclareLaunchArgument('archive_enabled',default_value='false'),
        DeclareLaunchArgument('capture_audio',default_value='true'),
        DeclareLaunchArgument('camera_enabled',default_value='false'),
        DeclareLaunchArgument('camera_device',default_value='/dev/video0'),
        DeclareLaunchArgument('recording_service',default_value='true'),
        DeclareLaunchArgument('record_dir',default_value='~/geniac_bags'),
        DeclareLaunchArgument('discord_enabled',default_value='false'),
        DeclareLaunchArgument('env_file',default_value=str(Path.home()/'geniac_ros2_ws/.env')),
        ExecuteProcess(cmd=['ros2','run','geniac_scenario','story_stock','--watch',
                            '--stock-dir',LaunchConfiguration('stock_dir'),'--env',LaunchConfiguration('env_file'),
                            '--opponent',LaunchConfiguration('opponent')],
                       condition=IfCondition(LaunchConfiguration('stock_enabled')),output='screen'),
        Node(sigterm_timeout='45',sigkill_timeout='10',respawn=True,respawn_delay=3.,package='geniac_detector',executable='detector',name='geniac_detector',output='screen',
             parameters=[LaunchConfiguration('detector_config'),sim,{'input_topic':LaunchConfiguration('input_topic')}]),
        Node(sigterm_timeout='45',sigkill_timeout='10',respawn=True,respawn_delay=3.,package='geniac_behavior',executable='classifier',name='geniac_behavior',output='screen',
             parameters=[LaunchConfiguration('behavior_config'),sim]),
        Node(sigterm_timeout='45',sigkill_timeout='10',respawn=True,respawn_delay=3.,package='geniac_scenario',executable='player',name='geniac_scenario',output='screen',parameters=[sim,{
            'tree_path':LaunchConfiguration('tree_path'),
            'stock_dir':LaunchConfiguration('stock_dir'),
            'use_stock':ParameterValue(LaunchConfiguration('stock_enabled'),value_type=bool),
            'auto_arm':ParameterValue(LaunchConfiguration('auto_arm'),value_type=bool),
            'dry_run':ParameterValue(LaunchConfiguration('dry_run'),value_type=bool),
            'auto_record':ParameterValue(LaunchConfiguration('auto_record'),value_type=bool)}]),
        Node(sigterm_timeout='45',sigkill_timeout='10',respawn=True,respawn_delay=3.,package='geniac_visualizer',executable='recorder',name='geniac_recorder',output='screen',
             condition=IfCondition(LaunchConfiguration('recording_service')),
             parameters=[{'output_dir':LaunchConfiguration('record_dir'),
                          'archive_enabled':ParameterValue(LaunchConfiguration('archive_enabled'),value_type=bool),
                          'capture_audio':ParameterValue(LaunchConfiguration('capture_audio'),value_type=bool),
                          'auto_record':ParameterValue(LaunchConfiguration('auto_record'),value_type=bool)}]),
        Node(sigterm_timeout='45',sigkill_timeout='10',respawn=True,respawn_delay=3.,package='geniac_visualizer',executable='cloud_preview',output='screen',parameters=[sim]),
        Node(sigterm_timeout='45',sigkill_timeout='10',respawn=True,respawn_delay=3.,package='geniac_visualizer',executable='microphone',output='screen'),
        Node(sigterm_timeout='45',sigkill_timeout='10',respawn=True,respawn_delay=3.,package='geniac_visualizer',executable='camera',name='geniac_camera',output='screen',
             condition=IfCondition(LaunchConfiguration('camera_enabled')),
             parameters=[sim,{'device':LaunchConfiguration('camera_device')}]),
        Node(sigterm_timeout='45',sigkill_timeout='10',respawn=True,respawn_delay=3.,package='geniac_visualizer',executable='discord_notifier',name='geniac_discord',output='screen',
             condition=IfCondition(LaunchConfiguration('discord_enabled')),
             parameters=[sim,{'enabled':True,'env_file':LaunchConfiguration('env_file')}]),
    ])
