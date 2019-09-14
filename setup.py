from setuptools import setup

setup(
    name='devops-pipeline',
    packages=['devops_pipeline'],
    include_package_data=True,
    install_requires=[
        'flask',
        'pydotplus',
        'networkx',
        'boto3',
        'ansible',
        'websockets',
        'flask-socketio',
        'eventlet',
        'python-socketio'
    ],
    entry_points = {
      "console_scripts": ['devops-pipeline=devops_pipeline.pipeline:main', 'parallel-pipeline=devops_pipeline.parallel:main']
    }
)
