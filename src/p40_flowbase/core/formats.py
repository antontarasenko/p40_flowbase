"""
MIT License

Copyright (c) 2025 Anton Tarasenko

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from enum import StrEnum


class CompositeFormat(StrEnum):
    FILES = "files"
    ZIP = "zip"
    TAR_ZST = "tar.zst"


class TableFormat(StrEnum):
    PARQUET = "parquet"
    CSV = "csv"
    TSV = "tsv"
    JSON = "json"


class FigureFormat(StrEnum):
    PKL = "pkl"
    PDF = "pdf"
    PNG = "png"
    SVG = "svg"


class ModelFormat(StrEnum):
    PKL = "pkl"
    JOBLIB = "joblib"


class DocumentFormat(StrEnum):
    MD = "md"
    PDF = "pdf"
    HTML = "html"
    BEAMER_PDF = "beamer.pdf"


class DBFormat(StrEnum):
    SQLITE = "sqlite"
