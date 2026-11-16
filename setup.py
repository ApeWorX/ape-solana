#!/usr/bin/env python
from setuptools import find_packages, setup

extras_require = {
    "test": [
        "pytest>=6.0",
        "pytest-xdist",
        "pytest-cov",
        "pytest-mock",
    ],
    "lint": [
        "black>=25.1.0,<26",
        "mypy>=1.15.0,<2",
        "types-setuptools",
        "types-requests",
        "flake8>=7.1.2,<8",
        "flake8-breakpoint>=1.1.0,<2",
        "flake8-print>=5.0.0,<6",
        "flake8-pydantic",
        "flake8-type-checking",
        "isort>=6.0.0,<7",
        "mdformat>=0.7.22",
        "mdformat-gfm>=0.3.5",
        "mdformat-frontmatter>=0.4.1",
        "mdformat-pyproject>=0.0.2",
    ],
    "release": [
        "setuptools>=75.6.0",
        "wheel",
        "twine",
    ],
    "dev": [
        "commitizen",
        "pre-commit",
        "pytest-watch",
        "IPython",
        "ipdb",
    ],
}

extras_require["dev"] = (
    extras_require["test"]
    + extras_require["lint"]
    + extras_require["release"]
    + extras_require["dev"]
)

with open("./README.md") as readme:
    long_description = readme.read()


setup(
    name="ape-solana",
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    description="""ape-solana: Ape Ecosystem Plugin for Solana""",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="ApeWorX Ltd.",
    author_email="admin@apeworx.io",
    url="https://github.com/ApeWorX/ape-solana",
    include_package_data=True,
    install_requires=[
        "click",  # Use same version as eth-ape
        "eth-ape>=0.8.54,<0.9",
        "eth-account",  # Use same version as eth-ape
        "eth-keyfile",  # Use same version as eth-ape
        "requests",  # Use same version as eth-ape
        "solders>=0.29.0,<0.30",
    ],
    entry_points={"ape_cli_subcommands": ["ape_solana=ape_solana._cli:cli"]},
    python_requires=">=3.10,<4",
    extras_require=extras_require,
    py_modules=["ape_solana"],
    license="Apache-2.0",
    zip_safe=False,
    keywords="solana",
    packages=find_packages(exclude=["tests", "tests.*"]),
    package_data={"ape_solana": ["py.typed"]},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Operating System :: MacOS",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
)
