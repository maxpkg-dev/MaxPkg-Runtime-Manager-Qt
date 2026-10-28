"""HTTP for the MaxPkg API and downloads through Qt's asynchronous QNetworkAccessManager.

Requests run in Qt's event loop: no Python threads, so nothing depends on the GIL (3ds Max 2022 keeps the
GIL while idle and Python worker threads barely ran), 3ds Max never blocks, and callbacks always arrive on
the main thread. Parsing uses the pure functions from domain/. Replies still running when the service stops
are aborted and their callbacks dropped.
"""

import importlib
import itertools
import os

from ..qt_compat import BINDING, QtCore
from . import log

QtNetwork = importlib.import_module(BINDING + ".QtNetwork")

USER_AGENT = b"MaxPkg-Package-Manager"
TIMEOUT_MS = 25000
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


class NetworkError(Exception):
    def __init__(self, message, status=0):
        Exception.__init__(self, message)
        self.status = status


def describe(error):
    """Short user-facing text for a failed request."""
    if isinstance(error, NetworkError):
        if error.status:
            return "The server answered HTTP {}.".format(error.status)
        return "The MaxPkg service could not be reached."
    return str(error) or error.__class__.__name__


class NetworkService(QtCore.QObject):
    def __init__(self, parent=None):
        QtCore.QObject.__init__(self, parent)
        self._manager = QtNetwork.QNetworkAccessManager(self)
        self._replies = {}
        self._tickets = itertools.count(1)
        self.stopped = False

    # --- requests ---------------------------------------------------------------------
    def _request(self, url):
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        request.setRawHeader(b"User-Agent", USER_AGENT)
        request.setAttribute(QtNetwork.QNetworkRequest.RedirectPolicyAttribute,
                             QtNetwork.QNetworkRequest.NoLessSafeRedirectPolicy)
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(TIMEOUT_MS)
        return request

    def post(self, endpoint, request, parse, on_done):
        """API call: POST the form, parse the text with `parse(text)`, then on_done(result, error)."""
        if self.stopped:
            return 0
        url = request.url(endpoint)
        qt_request = self._request(url)
        qt_request.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, "application/x-www-form-urlencoded")
        log.debug("network", "POST " + url)
        reply = self._manager.post(qt_request, QtCore.QByteArray(request.body()))
        return self._track(reply, lambda data: parse(data.decode("utf-8", "replace")), on_done)

    def download(self, url, target, on_done, max_bytes=MAX_DOWNLOAD_BYTES):
        """GET `url` into `target` through a .part file; on_done(target, error)."""
        if self.stopped:
            return 0
        folder = os.path.dirname(target)
        if folder:
            os.makedirs(folder, exist_ok=True)
        partial = target + ".part"
        stream = open(partial, "wb")
        reply = self._manager.get(self._request(url))
        received = [0]

        def on_ready_read():
            chunk = bytes(reply.readAll())
            received[0] += len(chunk)
            if received[0] > max_bytes:
                reply.abort()
                return
            stream.write(chunk)

        reply.readyRead.connect(on_ready_read)

        def finish(data):
            on_ready_read() if data else None
            stream.close()
            if received[0] > max_bytes:
                raise NetworkError("Download is larger than allowed")
            if received[0] == 0:
                raise NetworkError("Downloaded file is empty")
            os.replace(partial, target)
            return target

        def cleanup():
            if not stream.closed:
                stream.close()
            if os.path.exists(partial):
                try:
                    os.remove(partial)
                except OSError:
                    pass

        return self._track(reply, finish, on_done, cleanup, streaming=True)

    def _track(self, reply, convert, on_done, cleanup=None, streaming=False):
        ticket = next(self._tickets)
        self._replies[ticket] = reply

        def finished():
            self._replies.pop(ticket, None)
            result = error = None
            try:
                status = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
                status = int(status) if status is not None else 0
                if reply.error() != QtNetwork.QNetworkReply.NoError:
                    raise NetworkError(reply.errorString(), status if status >= 400 else 0)
                data = bytes(reply.readAll())
                result = convert(data if not streaming else data)
            except Exception as exception:  # noqa: BLE001 - reported to the caller
                error = exception
                if cleanup is not None:
                    cleanup()
            reply.deleteLater()
            if self.stopped or on_done is None:
                return
            try:
                on_done(result, error)
            except Exception as exception:  # noqa: BLE001 - one bad callback must not break the others
                log.error("network", "Callback failed: " + repr(exception))

        reply.finished.connect(finished)
        return ticket

    def forget(self, ticket):
        reply = self._replies.pop(ticket, None)
        if reply is not None:
            try:
                reply.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            reply.abort()
            reply.deleteLater()

    def busy(self):
        return bool(self._replies)

    def stop(self):
        """Abort everything still running; their callbacks are never called."""
        self.stopped = True
        for ticket in list(self._replies):
            self.forget(ticket)
        return True
