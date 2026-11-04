"""Log format that keeps a traceback only for failures that point at a bug in G3M."""

import copy
import logging
import os
import shutil
import subprocess
import tarfile
import traceback
import zipfile

import requests

from models.exceptions import G3MError

# Failures caused by the machine, the files or the network: the message says what happened, a traceback adds nothing.
_EXPECTED = (
    OSError,
    ValueError,
    EOFError,
    G3MError,
    zipfile.BadZipFile,
    tarfile.TarError,
    shutil.Error,
    subprocess.SubprocessError,
    requests.RequestException,
)
FULL_TRACEBACKS_ENV = "G3M_LOG_TRACEBACKS"
_SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _raised_at(error: BaseException) -> str:
    """The innermost frame inside G3M, so a one-line entry still says where to look."""
    frames = [frame for frame in traceback.extract_tb(error.__traceback__) if frame.filename.startswith(_SOURCE_ROOT)]
    return f" [{os.path.relpath(frames[-1].filename, _SOURCE_ROOT)}:{frames[-1].lineno}]" if frames else ""


def _describe(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
    text += _raised_at(error)
    cause = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    if cause is not None and str(cause) and str(cause) not in text:
        text += f" (caused by {type(cause).__name__}: {cause})"
    return text


class ConciseFormatter(logging.Formatter):
    """Shows an expected failure as one line; unexpected ones and critical records keep the full traceback."""

    def format(self, record: logging.LogRecord) -> str:
        info = record.exc_info
        error = info[1] if info else None
        if (
            error is not None
            and record.levelno < logging.CRITICAL
            and isinstance(error, _EXPECTED)
            and not os.environ.get(FULL_TRACEBACKS_ENV)
        ):
            record = copy.copy(record)
            record.exc_info = record.exc_text = None
            message = record.getMessage()
            already_said = bool(str(error)) and str(error) in message
            record.msg = (message + _raised_at(error)) if already_said else f"{message}: {_describe(error)}"
            record.args = None
        return super().format(record)
