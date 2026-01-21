"""Setup script for Genesis Mesh."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="genesis-mesh",
    version="0.1.0",
    author="Genesis Mesh Team",
    description="Secure decentralized mesh networking with cryptographic trust chains",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/genesis-mesh",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: System :: Networking",
        "Topic :: Security :: Cryptography",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "genesis-mesh=genesis_mesh.cli.main:main",
            "genesis-mesh-na=genesis_mesh.na_service.server:main",
            "genesis-mesh-node=genesis_mesh.node.node:main",
        ],
    },
)
