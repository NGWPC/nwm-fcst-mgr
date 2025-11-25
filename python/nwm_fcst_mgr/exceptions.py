class NgenCalledProcessError(Exception):
    """Raised when a call to ngen executable fails"""

    def __init__(self, cmd: str, cwd: str, returncode: int):
        self.returncode = returncode
        self.cmd = cmd
        self.cwd = cwd


class NgenIntentionallyStoppedError(Exception):
    """Raised when the ngen process is intentionally stopped."""

    def __init__(self, cmd: str, cwd: str, returncode: int):
        self.returncode = returncode
        self.cmd = cmd
        self.cwd = cwd
