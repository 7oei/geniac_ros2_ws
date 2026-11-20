from glob import glob
from setuptools import find_packages, setup
NAME = 'geniac_visualizer'
setup(name=NAME, version='0.1.0', packages=find_packages(exclude=['test']),
      data_files=[('share/ament_index/resource_index/packages', ['resource/' + NAME]),
                  ('share/' + NAME, ['package.xml']),
                  ('share/' + NAME + '/config', glob('config/*')),
                  ('share/' + NAME + '/models', glob('models/*')),
                  ('share/' + NAME + '/launch', glob('launch/*.py'))],
      install_requires=['setuptools'], zip_safe=False,
      maintainer='GENIAC developers', maintainer_email='kulala.mbili@gmail.com',
      description='Mother desktop visualization and remote bag recording', license='Proprietary', tests_require=['pytest'],
      entry_points={'console_scripts': ['dashboard = geniac_visualizer.dashboard:main', 'recorder = geniac_visualizer.recorder_node:main', 'discord_notifier = geniac_visualizer.discord_node:main']})
