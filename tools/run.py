"""Utility to run shell commands asynchronously with a timeout."""

import asyncio
import subprocess

TRUNCATED_MESSAGE: str = "<response clipped><NOTE>To save on context only part of this file has been shown to you. You should retry this tool after you have searched inside the file with `grep -n` in order to find the line numbers of what you are looking for.</NOTE>"
MAX_RESPONSE_LEN: int = 16000


def maybe_truncate(content: str, truncate_after: int | None = MAX_RESPONSE_LEN):
    """Truncate content and append a notice if content exceeds the specified length."""
    return (
        content
        if not truncate_after or len(content) <= truncate_after
        else content[:truncate_after] + TRUNCATED_MESSAGE
    )


async def run(
    cmd: str,
    timeout: float | None = 120.0,  # seconds
    truncate_after: int | None = MAX_RESPONSE_LEN,
):
    """Run a shell command asynchronously with a timeout."""
    loop = asyncio.get_running_loop()

    try:
        # Run the command in a separate thread using run_in_executor
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: subprocess.run(cmd, shell=True, capture_output=True)
            ),
            timeout=timeout,
        )

        stdout = maybe_truncate(result.stdout.decode(errors="replace"), truncate_after=truncate_after)
        stderr = maybe_truncate(result.stderr.decode(errors="replace"), truncate_after=truncate_after)
        return result.returncode, stdout, stderr

    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"Command '{cmd}' timed out after {timeout} seconds"
        ) from exc