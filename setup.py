from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()


setup(
    name='newsdataapi',
    version='0.1.18',
    packages=['newsdataapi'],
    description='Python library for newsdata client-API Call',
    long_description=long_description,
    long_description_content_type="text/markdown",
    url='https://github.com/newsdataapi/python-client',
    author='NewsData.io',
    author_email='contact@newsdata.io',
    license='MIT',
    install_requires=["requests<3.0.0"],
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
    test_suite='tests',    
    python_requires='>=3.5',
    keywords=[
        'news',
        'news data',
        ],
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Customer Service",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
      ] 

)
