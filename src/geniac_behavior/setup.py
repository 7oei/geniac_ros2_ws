from glob import glob
from setuptools import find_packages, setup
NAME = 'geniac_behavior'
setup(name=NAME, version='0.1.0', packages=find_packages(exclude=['test']),
      data_files=[('share/ament_index/resource_index/packages', ['resource/' + NAME]),
                  ('share/' + NAME, ['package.xml']),
                  ('share/' + NAME + '/config', glob('config/*')),
                  ('share/' + NAME + '/models', glob('models/*')),
                  ('share/' + NAME + '/launch', glob('launch/*.py'))],
      install_requires=['setuptools'], zip_safe=False,
      maintainer='GENIAC developers', maintainer_email='kulala.mbili@gmail.com',
      description='Trajectory-based deer response classification', license='Proprietary', tests_require=['pytest'],
      entry_points={'console_scripts': ['classifier = geniac_behavior.node:main', 'manual_test = geniac_behavior.manual_gui:main', 'replay_test = geniac_behavior.manual_session:main']})
