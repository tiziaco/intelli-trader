import os
from setuptools import setup, find_packages
from setuptools import setup

with open('requirements.txt') as f:
    required = f.read().splitlines()

setup(
    name = 'itrade',
    version = '0.1.0',
    url = 'https://github.com/tiziaco/IntelliTrade.com',
    description = '',
    packages = find_packages(),
    install_requires = required
)
