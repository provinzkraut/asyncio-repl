# Most of this code was adapted from
# https://github.com/python/cpython/blob/80b9e79d84e835ecdb5a15c9ba73e44803ca9d32/Lib/asyncio/__main__.py

import ast
import asyncio
import concurrent.futures
import contextvars
import inspect
import os
import site
import sys
import threading
import types
import warnings

try:
    from _colorize import can_colorize, ANSIColors  # type: ignore[import-not-found]
except ImportError:
    can_colorize = None
    ANSIColors = None

if sys.version_info >= (3, 13):
    from _pyrepl.console import InteractiveColoredConsole as BaseConsole  # type: ignore[import-not-found]
else:
    from code import InteractiveConsole as BaseConsole

from asyncio import futures
from typing import Any, NoReturn, Optional, Union


class AsyncIOInteractiveConsole(BaseConsole):
    def __init__(self, local: dict[str, Any], loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(local, filename="<stdin>")
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

        self.loop = loop
        self.context = contextvars.copy_context()
        self.repl_future: Optional[asyncio.Future[Any]] = None
        self.keyboard_interrupted: bool = False
        self.return_code: Union[str, int, None] = 0

    def runcode(self, code: types.CodeType) -> Any:
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()

        def callback() -> None:
            func = types.FunctionType(code, self.locals)  # type: ignore[arg-type]
            try:
                coro = func()
            except SystemExit as se:
                self.return_code = se.code
                self.loop.stop()
                return
            except KeyboardInterrupt as ex:
                self.keyboard_interrupted = True
                future.set_exception(ex)
                return
            except BaseException as ex:
                future.set_exception(ex)
                return

            if not inspect.iscoroutine(coro):
                future.set_result(coro)
                return

            try:
                if sys.version_info >= (3, 11):
                    self.repl_future = self.loop.create_task(coro, context=self.context)
                else:
                    self.repl_future = self.loop.create_task(coro)

                futures._chain_future(self.repl_future, future)  # type: ignore[attr-defined]
            except BaseException as exc:
                future.set_exception(exc)

        self.loop.call_soon_threadsafe(callback, context=self.context)

        try:
            return future.result()
        except SystemExit as se:
            self.return_code = se.code
            self.loop.stop()
            return
        except BaseException:
            if self.keyboard_interrupted:
                self.write("\nKeyboardInterrupt\n")
            else:
                self.showtraceback()


class REPLThread(threading.Thread):
    def __init__(
        self,
        name: str,
        console: AsyncIOInteractiveConsole,
        can_use_pyrepl: bool,
        banner: Optional[str] = None,
    ) -> None:
        super().__init__(name=name)
        self.console = console
        self.can_use_pyrepl = can_use_pyrepl
        if banner is None:
            banner = (
                f"asyncio REPL {sys.version} on {sys.platform}\n"
                f'Use "await" directly instead of "asyncio.run()".\n'
                f'Type "help", "copyright", "credits" or "license" '
                f"for more information.\n"
            )
        self.banner = banner

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self.console.loop

    def run(self) -> None:
        try:
            self.console.write(self.banner)

            if startup_path := os.getenv("PYTHONSTARTUP"):
                sys.audit("cpython.run_startup", startup_path)

                import tokenize

                with tokenize.open(startup_path) as f:
                    startup_code = compile(f.read(), startup_path, "exec")
                    exec(startup_code, self.console.locals)  # type: ignore[arg-type]

            ps1 = getattr(sys, "ps1", ">>> ")
            if can_colorize is not None and can_colorize() and self.can_use_pyrepl:
                ps1 = f"{ANSIColors.BOLD_MAGENTA}{ps1}{ANSIColors.RESET}"
            self.console.write(f"{ps1}import asyncio\n")

            if self.can_use_pyrepl:
                from _pyrepl.simple_interact import (  # type: ignore[import-not-found]
                    run_multiline_interactive_console,
                )

                try:
                    run_multiline_interactive_console(self.console)
                except SystemExit:
                    # expected via the `exit` and `quit` commands
                    pass
                except BaseException:
                    # unexpected issue
                    self.console.showtraceback()
                    self.console.write("Internal error, ")
                    self.console.return_code = 1
            else:
                self.console.interact(banner="", exitmsg="")
        finally:
            warnings.filterwarnings(
                "ignore",
                message=r"^coroutine .* was never awaited$",
                category=RuntimeWarning,
            )

            self.loop.call_soon_threadsafe(self.loop.stop)

    def interrupt(self) -> None:
        if not self.can_use_pyrepl:
            return

        from _pyrepl.simple_interact import _get_reader

        r = _get_reader()
        if r.threading_hook is not None:
            r.threading_hook.add("")


def interact(
    banner: Optional[str] = None,
    local: Optional[dict[str, Any]] = None,
    exitmsg: Optional[str] = None,
) -> NoReturn:
    sys.audit("cpython.run_stdin")

    if os.getenv("PYTHON_BASIC_REPL"):
        CAN_USE_PYREPL = False
    else:
        try:
            from _pyrepl.main import CAN_USE_PYREPL  # type: ignore[import-not-found, no-redef]
        except ImportError:
            CAN_USE_PYREPL = False

    loop = asyncio.new_event_loop()
    if sys.version_info < (3, 14):
        asyncio.set_event_loop(loop)
    else:
        asyncio._set_event_loop(loop)

    repl_locals = {"asyncio": asyncio}
    for key in {
        "__name__",
        "__package__",
        "__loader__",
        "__spec__",
        "__builtins__",
        "__file__",
    }:
        repl_locals[key] = globals()[key]

    if local is not None:
        repl_locals.update(local)

    console = AsyncIOInteractiveConsole(repl_locals, loop)

    try:
        import readline  # NoQA
    except ImportError:
        readline = None  # type: ignore[assignment]

    interactive_hook = getattr(sys, "__interactivehook__", None)

    if interactive_hook is not None:
        sys.audit("cpython.run_interactivehook", interactive_hook)
        interactive_hook()

    if hasattr(site, "register_readline"):
        if interactive_hook is site.register_readline:
            # Fix the completer function to use the interactive console locals
            try:
                import rlcompleter
            except:  # noqa: E722
                pass
            else:
                if readline is not None:
                    completer = rlcompleter.Completer(console.locals)  # type: ignore[arg-type]
                    readline.set_completer(completer.complete)

    repl_thread = REPLThread(
        name="Interactive thread",
        console=console,
        can_use_pyrepl=CAN_USE_PYREPL,
        banner=banner,
    )
    repl_thread.daemon = True
    repl_thread.start()

    while True:
        try:
            console.loop.run_forever()
        except KeyboardInterrupt:
            console.keyboard_interrupted = True
            if console.repl_future and not console.repl_future.done():
                console.repl_future.cancel()
            repl_thread.interrupt()
            continue
        else:
            break

    console.write(exitmsg or "exiting asyncio REPL...\n")
    sys.exit(console.return_code)
