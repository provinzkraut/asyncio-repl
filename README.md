# Asyncio REPL

Backport of [Python 3.14's asyncio REPL](https://github.com/python/cpython/blob/80b9e79d84e835ecdb5a15c9ba73e44803ca9d32/Lib/asyncio/__main__.py),
made available as a standalone module to enable programatic access.

The functionality provided herein has been proposed to be [added to the stdlib in 
Python 3.14](https://discuss.python.org/t/add-asyncio-console-module-to-progamatically-access-the-asyncio-repl/79919).

Should this proposal be accepted, this package is intended to serve as a backport to 
older Python versions.


## Usage 

You can use to get the same `python -m asyncio`  REPL available under Python 3.14 with:

```shell
python -m asyncio_repl
```

or invoke the REPL programmatically by using the `interact` function, which follows the
same semantics as the stdlib's 
[`code.interact`](https://docs.python.org/3/library/code.html#code.interact):

```python
from asyncio_repl import interact

interact(
    banner="Welcome to my REPL", 
    exitmsg="Goodbye", 
    local={"some_name": "some_value"},
)
```
