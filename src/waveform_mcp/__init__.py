"""Waveform MCP Server - RTL waveform analysis using WAL.

This package provides a Model Context Protocol (MCP) server that enables
LLMs to analyze waveform files from RTL simulations. It uses WAL (Waveform
Analysis Language) to parse and analyze VCD and FST waveform files.

Key features:
- Signal discovery and inspection
- Basic signal analysis
- Extensible WAL expression interface

Supported formats: VCD, FST (via WAL)
"""

__version__ = "0.1.0"
__author__ = "Yossi Nivin"