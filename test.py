# Most of this code was adapted from
# https://github.com/python/cpython/blob/80b9e79d84e835ecdb5a15c9ba73e44803ca9d32/Lib/test/test_repl.py

import os
import select
import subprocess
import sys
import unittest
from textwrap import dedent
import pytest


def kill_python(p):
    """Run the given Popen process until completion and return stdout."""
    p.stdin.close()
    data = p.stdout.read()
    p.stdout.close()
    # try to cleanup the child so we don't appear to leak when running
    # with regrtest -R.
    p.wait()
    subprocess._cleanup()
    return data


try:
    import pty
except ImportError:
    pty = None


def spawn_repl(*args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw):
    """Run the Python REPL with the given arguments.

    kw is extra keyword args to pass to subprocess.Popen. Returns a Popen
    object.
    """

    # To run the REPL without using a terminal, spawn python with the command
    # line option '-i' and the process name set to '<stdin>'.
    # The directory of argv[0] must match the directory of the Python
    # executable for the Popen() call to python to succeed as the directory
    # path may be used by Py_GetPath() to build the default module search
    # path.
    stdin_fname = os.path.join(os.path.dirname(sys.executable), "<stdin>")
    cmd_line = [stdin_fname, "-I", "-i"]
    cmd_line.extend(args)

    # Set TERM=vt100, for the rationale see the comments in spawn_python() of
    # test.support.script_helper.
    env = kw.setdefault("env", dict(os.environ))
    env["TERM"] = "vt100"
    return subprocess.Popen(
        cmd_line,
        executable=sys.executable,
        text=True,
        stdin=subprocess.PIPE,
        stdout=stdout,
        stderr=stderr,
        **kw,
    )


def spawn_console(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT):
    cmd_line = [sys.executable, "-c", f"from asyncio_repl import interact;{cmd}"]
    return subprocess.Popen(
        cmd_line,
        executable=sys.executable,
        text=True,
        stdin=subprocess.PIPE,
        stdout=stdout,
        stderr=stderr,
    )


class TestInteractiveInterpreter:
    def test_asyncio_repl_reaches_python_startup_script(self, tmp_path):
        script = os.path.join(str(tmp_path), "pythonstartup.py")
        with open(script, "w") as f:
            f.write("print('pythonstartup done!')" + os.linesep)
            f.write("exit(0)" + os.linesep)

        env = os.environ.copy()
        env["PYTHON_HISTORY"] = os.path.join(str(tmp_path), ".asyncio_history")
        env["PYTHONSTARTUP"] = script
        subprocess.check_call(
            [sys.executable, "-m", "asyncio"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=5,
        )

    @unittest.skipUnless(pty, "requires pty")
    def test_asyncio_repl_is_ok(self):
        m, s = pty.openpty()
        cmd = [sys.executable, "-I", "-m", "asyncio"]
        env = os.environ.copy()
        proc = subprocess.Popen(
            cmd,
            stdin=s,
            stdout=s,
            stderr=s,
            text=True,
            close_fds=True,
            env=env,
        )
        os.close(s)
        os.write(m, b"await asyncio.sleep(0)\n")
        os.write(m, b"exit()\n")
        output = []
        while select.select([m], [], [], 1)[0]:
            try:
                data = os.read(m, 1024).decode("utf-8")
                if not data:
                    break
            except OSError:
                break
            output.append(data)
        os.close(m)
        try:
            exit_code = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            exit_code = proc.wait()

        assert exit_code == 0

    def test_toplevel_contextvars_sync(self):
        user_input = dedent("""\
        from contextvars import ContextVar
        var = ContextVar("var", default="failed")
        var.set("ok")
        """)
        p = spawn_repl("-m", "asyncio_repl")
        p.stdin.write(user_input)
        user_input2 = dedent("""
        print(f"toplevel contextvar test: {var.get()}")
        """)
        p.stdin.write(user_input2)
        output = kill_python(p)
        assert p.returncode == 0
        expected = "toplevel contextvar test: ok"
        assert expected in output

    @pytest.mark.skipif(sys.version_info <= (3, 11), reason="")
    def test_toplevel_contextvars_async(self):
        user_input = dedent("""\
        from contextvars import ContextVar
        var = ContextVar('var', default='failed')
        """)
        p = spawn_repl("-m", "asyncio_repl")
        p.stdin.write(user_input)
        user_input2 = "async def set_var(): var.set('ok')\n\n"
        p.stdin.write(user_input2)
        user_input3 = "await set_var()\n"
        p.stdin.write(user_input3)
        user_input4 = "print(f'toplevel contextvar test: {var.get()}')\n"
        p.stdin.write(user_input4)
        output = kill_python(p)
        assert p.returncode == 0
        expected = "toplevel contextvar test: ok"
        assert expected in output


class TestInteract:
    def test_set_banner(self):
        p = spawn_console("interact(banner='hello from my console')")
        output = kill_python(p)
        assert p.returncode == 0
        assert output.startswith("hello from my console")

    def test_set_exitmsg(self):
        p = spawn_console("interact(exitmsg='quitting console')")
        output = kill_python(p)
        assert p.returncode == 0
        assert output.endswith("quitting console")

    def test_set_local(self):
        p = spawn_console("interact(local={'my_var': 'content of my_var'})")
        p.stdin.write("my_var")
        output = kill_python(p)
        assert p.returncode == 0
        assert "content of my_var" in output
