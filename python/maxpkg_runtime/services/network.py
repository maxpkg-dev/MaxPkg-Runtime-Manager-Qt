"""Background HTTP for the Runtime API and downloads.

Workers run plain Python (urllib + pure parsers from domain/). They never touch pymxs, Qt widgets
or Runtime state. Results come back to the main thread through a queued signal and are dropped
when the service was stopped or the caller's generation is stale.
"""

import itertools
import os
import ssl
import threading
import urllib.error
import urllib.request

from ..qt_compat import QtCore, Signal
from . import log

USER_AGENT = "MaxPkg-Runtime-Qt"
TIMEOUT_SECONDS = 25


class _Relay(QtCore.QObject):
    finished = Signal(int, object, object)  # ticket, result, error


class _Task(QtCore.QRunnable):
    def __init__(self, ticket, work, relay, cancelled):
        QtCore.QRunnable.__init__(self)
        self.setAutoDelete(True)
        self.ticket = ticket
        self.work = work
        self.relay = relay
        self.cancelled = cancelled

    def run(self):
        if self.cancelled.is_set():
            return
        result = error = None
        try:
            result = self.work(self.cancelled)
        except Exception as exception:  # noqa: BLE001 - reported to the caller on the main thread
            error = exception
        if not self.cancelled.is_set():
            self.relay.finished.emit(self.ticket, result, error)


def _context():
    context = ssl.create_default_context()  # Windows certificate store
    return context


def http_post(url, body, cancelled=None):
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=_context()) as response:
        return response.read().decode("utf-8", errors="replace")


def http_download(url, target, cancelled=None, max_bytes=200 * 1024 * 1024):
    """Download to `target` through a .part file. Returns the final path."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    partial = target + ".part"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    received = 0
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=_context()) as response, \
            open(partial, "wb") as stream:
        while True:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("Download cancelled")
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > max_bytes:
                raise RuntimeError("Download is larger than allowed")
            stream.write(chunk)
    if received == 0:
        raise RuntimeError("Downloaded file is empty")
    os.replace(partial, target)
    return target


def describe(error):
    """Short user-facing text for a worker exception."""
    if isinstance(error, urllib.error.HTTPError):
        return "The server answered HTTP {}.".format(error.code)
    if isinstance(error, (urllib.error.URLError, OSError)):
        return "The Runtime API could not be reached."
    return str(error) or error.__class__.__name__


class NetworkService(QtCore.QObject):
    """Runs callables in Qt's global pool; `submit` returns a ticket, callbacks run on the main thread.

    Lifetime rules (see PITFALLS.md): the relay has no Qt parent and every task keeps a reference to
    it, so a request that is still blocked in urlopen after stop() emits into a live object whose
    signal is already disconnected. We never own a QThreadPool: destroying one blocks until all
    running requests time out.
    """

    def __init__(self, parent=None):
        QtCore.QObject.__init__(self, parent)
        self._pool = QtCore.QThreadPool.globalInstance()
        self._relay = _Relay()
        self._relay.finished.connect(self._on_finished)
        self._callbacks = {}
        self._tickets = itertools.count(1)
        self._cancelled = threading.Event()
        self.stopped = False

    def submit(self, work, on_done):
        """work(cancelled_event) -> result in a worker; on_done(result, error) on the main thread."""
        if self.stopped:
            return 0
        ticket = next(self._tickets)
        self._callbacks[ticket] = on_done
        self._pool.start(_Task(ticket, work, self._relay, self._cancelled))
        return ticket

    def forget(self, ticket):
        self._callbacks.pop(ticket, None)

    def post(self, endpoint, request, parse, on_done):
        """API call: POST `request`, parse the text in the worker with `parse(text)`."""
        url = request.url(endpoint)

        def work(_cancelled):
            log.debug("network", "POST " + url)
            return parse(http_post(url, request.body()))

        return self.submit(work, on_done)

    def busy(self):
        return bool(self._callbacks)

    def _on_finished(self, ticket, result, error):
        callback = self._callbacks.pop(ticket, None)
        if callback is None or self.stopped:
            return
        try:
            callback(result, error)
        except Exception as exception:  # noqa: BLE001 - one bad callback must not kill the relay
            log.error("network", "Callback failed: " + repr(exception))

    def stop(self):
        """Cancel queued work and detach from running workers; their late results are dropped."""
        self.stopped = True
        self._cancelled.set()
        self._callbacks.clear()
        try:
            self._relay.finished.disconnect(self._on_finished)
        except (RuntimeError, TypeError):
            pass
        return True
