from glob import glob
from setuptools import find_packages, setup
NAME = 'geniac_scenario'
setup(name=NAME, version='0.1.0', packages=find_packages(exclude=['test']),
      data_files=[('share/ament_index/resource_index/packages', ['resource/' + NAME]),
                  ('share/' + NAME, ['package.xml']),
                  ('share/' + NAME + '/config', glob('config/*')),
                  ('share/' + NAME + '/models', glob('models/*')),
                  ('share/' + NAME + '/launch', glob('launch/*.py'))],
      install_requires=['setuptools'], zip_safe=False,
      maintainer='GENIAC developers', maintainer_email='kulala.mbili@gmail.com',
      description='Offline scenario trees and reaction-driven audio playback', license='Proprietary', tests_require=['pytest'],
      entry_points={'console_scripts': ['bag_test = geniac_scenario.bag_test:main', 'integration_test = geniac_scenario.integration:main', 'story_stock = geniac_scenario.stock:main', 'manual_test = geniac_scenario.manual_gui:main', 'player = geniac_scenario.node:main', 'prepare_tree = geniac_scenario.prepare:main', 'sound_assets = geniac_scenario.assets:main']})
