"""Typed exceptions used to map failure modes to CLI exit codes.

Exit code mapping (handled in cli.main):
  0   success
  1   UsageError (bad args, unreadable input file, etc.)
  2   NoUsablePhotosError
  3   FFmpegError
  130 KeyboardInterrupt (handled in cli.main, no exception class needed)
"""


class SlideshowError(Exception):
    """Base class for all tool errors."""


class UsageError(SlideshowError):
    """Bad CLI usage or unreadable input file."""


class NoUsablePhotosError(SlideshowError):
    """Input contained no decodable, supported images."""


class FFmpegError(SlideshowError):
    """ffmpeg subprocess returned non-zero."""

    def __init__(self, returncode: int, stderr: str):
        super().__init__(f"ffmpeg failed with code {returncode}")
        self.returncode = returncode
        self.stderr = stderr
