#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Setup script for Voxtral Notetaker
"""

from setuptools import setup, find_packages

with open("requirements.txt", "r") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="voxtral-notetaker",
    version="1.0.0",
    description="Raspberry Pi based meeting notes recognition and transcription system using Voxtral 4",
    author="Outthinkx by Luca De Simoni",
    license="MIT",
    packages=find_packages(),
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
        "License :: OSI Approved :: MIT License",
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
