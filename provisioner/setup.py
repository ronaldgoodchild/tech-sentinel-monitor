"""Provisioner CLI — pip install -e provisioner/"""

from setuptools import find_packages, setup

setup(
    name="ts-provisioner",
    version="1.0.0",
    description="Tech Sentinel Monitor — Provisioner CLI",
    author="Ronald Goodchild",
    author_email="ron@regteches.com",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.27",
        "click>=8.1",
    ],
    entry_points={
        "console_scripts": [
            "ts-provisioner=ts_provisioner.cli:cli",
        ],
    },
    python_requires=">=3.10",
)
