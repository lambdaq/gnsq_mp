#!/usr/bin/env python
# coding=utf-8

from setuptools import setup, find_packages

setup(
    name='gnsq_mp',
    version="0.2.2",
    # packages=find_packages('src'),
    packages=['gnsq_mp'],
    install_requires=[
        "gevent",
        "gnsq>=0.4.0",
    ],
    url="https://github.com/lambdaq/gnsq_mp",
    author="lambdaq",
    author_email="lambdaq@gmail.com",
    description="see README.md",
    long_description=open('README.md').read(),
    license="BSD"
)
