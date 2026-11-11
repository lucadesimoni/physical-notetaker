#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Setup script for Voxtral Notetaker
"""

import re

from setuptools import setup, find_packages

# The version lives in one place: voxtral_notetaker/__init__.py
with open("voxtral_notetaker/__init__.py", encoding="utf-8") as f:
    VERSION = re.search(r'^__version__ = "([^"]+)"', f.read(), re.M).group(1)

with open("requirements.txt", "r") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="voxtral-notetaker",
    version=VERSION,
    description="Meeting notetaker for Raspberry Pi and Windows: Mistral Voxtral transcription, Swiss German, memos and tasks",
    author="Outthinkx by Luca De Simoni",
    license="PolyForm-Noncommercial-1.0.0",
    packages=find_packages(),
    package_data={"voxtral_notetaker": ["data/*.txt"]},
    install_requires=requirements,
    extras_require={
        "local-diarization": ["pyannote.audio>=3.1.1"],
        # Buttons and status LED (on Raspberry Pi OS these come from apt)
        "device": ["gpiozero>=2.0", "evdev>=1.6"],
    },
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "voxtral-notetaker=voxtral_notetaker.cli:cli",
            "notetaker=voxtral_notetaker.cli:cli",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Sound/Audio",
        "Topic :: Office/Business :: Groupware",
        "Topic :: Utilities",
    ],
    keywords="voxtral transcription meeting notes raspberry-pi audio",
    project_urls={
        "Bug Reports": "https://github.com/lucadesimoni/physical-notetaker/issues",
        "Source": "https://github.com/lucadesimoni/physical-notetaker",
    },
)
