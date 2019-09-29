from setuptools import setup

setup(
    name='devops-pipeline',
    packages=['devops_pipeline'],
    version='0.1',
    description='infrastructure as code, pipeline tool',
    author='Samuel Squire',
    author_email='sam@samsquire.com',
    url='https://github.com/samsquire/devops-pipeline',
    include_package_data=True,
    install_requires=[
        'flask',
        'pydotplus',
        'psutil',
        'networkx',
        'boto3',
        'ansible',
        'websockets',
        'flask-socketio',
        'eventlet',
        'python-socketio',
        'SQLAlchemy',
        'parallel-ssh'
    ],
    entry_points = {
      "console_scripts": ['devops-pipeline=devops_pipeline.pipeline:main']
    },
     package_data={'web': ['devops_pipeline/web/*']},
     classifiers=[
        'Development Status :: 3 - Alpha',
        'Topic :: Software Development :: Build Tools',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6'
        ]
)
