from __future__ import annotations

import asyncio
import os


if os.name == "posix":
    from asyncio import unix_events

    class PipeSelectorEventLoop(unix_events._UnixSelectorEventLoop):
        def _make_self_pipe(self) -> None:
            self._ssock, self._csock = os.pipe()
            os.set_blocking(self._ssock, False)
            os.set_blocking(self._csock, False)
            self._internal_fds += 1
            self._add_reader(self._ssock, self._read_from_self)

        def _read_from_self(self) -> None:
            while True:
                try:
                    data = os.read(self._ssock, 4096)
                    if not data:
                        break
                    self._process_self_data(data)
                except (InterruptedError, BlockingIOError):
                    break

        def _write_to_self(self) -> None:
            if self._csock is None:
                return
            try:
                os.write(self._csock, b"\0")
            except OSError:
                pass

        def _close_self_pipe(self) -> None:
            self._remove_reader(self._ssock)
            os.close(self._ssock)
            self._ssock = None
            os.close(self._csock)
            self._csock = None
            self._internal_fds -= 1

    class PipeEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self):
            return PipeSelectorEventLoop()


def install_asyncio_policy() -> None:
    if os.name != "posix":
        return
    asyncio.set_event_loop_policy(PipeEventLoopPolicy())
