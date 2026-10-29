"""HTTP for the MaxPkg API and downloads through Qt's asynchronous QNetworkAccessManager, with a curl fallback.

Requests run in Qt's event loop: no Python threads, so nothing depends on the GIL (3ds Max 2022 keeps the
GIL while idle and Python worker threads barely ran), 3ds Max never blocks, and callbacks always arrive on
the main thread. Parsing uses the pure functions from domain/. Replies still running when the service stops
are aborted and their callbacks dropped.

Requests use the Windows proxy settings. When a request fails before any HTTP answer (a firewall that blocks
3ds Max, a proxy or TLS inspection Qt cannot pass), it is repeated with Windows' own curl.exe in a hidden
QProcess, still asynchronous. Once curl succeeds where Qt failed, the rest of the session goes through curl,
like the MaxScript Runtime's fallback. HTTP errors (4xx/5xx) are real answers and never switch.
"""

import importlib
import itertools
import os
import shutil
import tempfile

from ..domain.messages import without_links
from ..qt_compat import BINDING, QtCore
from . import log

QtNetwork = importlib.import_module(BINDING + ".QtNetwork")

USER_AGENT = b"MaxPkg-Package-Manager"
TIMEOUT_MS = 25000
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
CURL_CONNECT_SECONDS = 12
CURL_REQUEST_SECONDS = 90
CURL_DOWNLOAD_SECONDS = 600


class NetworkError(Exception):
    def __init__(self, message, status=0):
        Exception.__init__(self, message)
        self.status = status


def describe(error):
    """Short user-facing text for a failed request: no addresses or file paths (the log keeps the details)."""
    if isinstance(error, NetworkError):
        if error.status:
            return "The server answered HTTP {}.".format(error.status)
        return "The MaxPkg service could not be reached."
    if isinstance(error, OSError):  # str() of an OSError names the file, and so the Windows user name
        return "The download could not be saved: {}.".format((error.strerror or "disk error").rstrip("."))
    return without_links(str(error)) or error.__class__.__name__


def curl_executable():
    """Windows 10 1803+ ships curl.exe in System32; an empty string when it is missing."""
    system_root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    candidate = os.path.join(system_root, "System32", "curl.exe")
    return candidate if os.path.isfile(candidate) else ""


class NetworkService(QtCore.QObject):
    def __init__(self, parent=None):
        QtCore.QObject.__init__(self, parent)
        self._manager = QtNetwork.QNetworkAccessManager(self)
        self._replies = {}  # ticket -> (QNetworkReply or QProcess, cleanup or None)
        self._tickets = itertools.count(1)
        self._proxy_ready = False
        self._proxy_url = ""  # the system HTTP proxy, also given to curl
        self.curl = curl_executable()
        self.curl_mode = False  # True after curl worked where Qt did not: later requests go straight to curl
        self.stopped = False

    # --- system proxy -------------------------------------------------------------------
    def _use_system_proxy(self, url):
        """Read the Windows proxy once, at the first request (start() and scan() never touch the network)."""
        if self._proxy_ready:
            return
        self._proxy_ready = True
        try:
            proxies = QtNetwork.QNetworkProxyFactory.systemProxyForQuery(QtNetwork.QNetworkProxyQuery(QtCore.QUrl(url)))
        except Exception as exception:  # noqa: BLE001 - a broken proxy setup must not stop requests
            log.warning("network", "Could not read the system proxy: " + repr(exception))
            return
        proxy = proxies[0] if proxies else None
        if proxy is None or proxy.type() in (QtNetwork.QNetworkProxy.NoProxy, QtNetwork.QNetworkProxy.DefaultProxy):
            return
        self._manager.setProxy(proxy)
        if proxy.type() == QtNetwork.QNetworkProxy.HttpProxy and proxy.hostName():
            self._proxy_url = "http://{}:{}".format(proxy.hostName(), proxy.port())
        log.info("network", "Using the system proxy {}:{}".format(proxy.hostName(), proxy.port()))

    # --- requests ---------------------------------------------------------------------
    def _request(self, url):
        self._use_system_proxy(url)
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
        body = request.body()
        ticket = next(self._tickets)

        def convert(data):
            return parse(data.decode("utf-8", "replace"))

        def by_curl():
            self._curl(ticket, url, on_done, convert=convert, body=body)

        if self.curl_mode:
            by_curl()
            return ticket
        qt_request = self._request(url)
        qt_request.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, "application/x-www-form-urlencoded")
        log.debug("network", "POST " + url)
        reply = self._manager.post(qt_request, QtCore.QByteArray(body))
        self._watch(ticket, reply, convert, on_done, retry=by_curl)
        return ticket

    def download(self, url, target, on_done, max_bytes=MAX_DOWNLOAD_BYTES):
        """GET `url` into `target` through a .part file; on_done(target, error)."""
        if self.stopped:
            return 0
        folder = os.path.dirname(target)
        if folder:
            os.makedirs(folder, exist_ok=True)
        partial = target + ".part"
        ticket = next(self._tickets)

        def by_curl():
            self._curl(ticket, url, on_done, target=target, max_bytes=max_bytes)

        if self.curl_mode:
            by_curl()
            return ticket
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
            _remove(partial)

        self._watch(ticket, reply, finish, on_done, cleanup, retry=by_curl,
                    too_large=lambda: received[0] > max_bytes)
        return ticket

    def _watch(self, ticket, reply, convert, on_done, cleanup=None, retry=None, too_large=None):
        self._replies[ticket] = (reply, cleanup)

        def finished():
            self._replies.pop(ticket, None)
            result = error = None
            status = 0
            try:
                status = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
                status = int(status) if status is not None else 0
                if reply.error() != QtNetwork.QNetworkReply.NoError:
                    raise NetworkError(reply.errorString(), status if status >= 400 else 0)
                result = convert(bytes(reply.readAll()))
            except Exception as exception:  # noqa: BLE001 - reported to the caller
                error = exception
                if cleanup is not None:
                    cleanup()
            reply.deleteLater()
            if self.stopped or on_done is None:
                return
            no_answer = isinstance(error, NetworkError) and not status and not (too_large and too_large())
            if no_answer and retry is not None and self.curl:
                log.warning("network", "Qt request failed ({}); trying curl".format(error))
                retry()
                return
            _deliver(on_done, result, error)

        reply.finished.connect(finished)

    # --- curl fallback ----------------------------------------------------------------
    def _curl(self, ticket, url, on_done, convert=None, body=None, target=None, max_bytes=MAX_DOWNLOAD_BYTES):
        """The same request through curl.exe: POST `body` and convert the answer, or download into `target`."""
        if not self.curl:
            _deliver(on_done, None, NetworkError("curl.exe is not available"))
            return
        work = tempfile.mkdtemp(prefix="maxpkg-curl-")
        output = target + ".part" if target else os.path.join(work, "response")
        secure = url.lower().startswith("https://")
        arguments = ["--silent", "--show-error", "--location", "--fail",
                     "--proto", "=https" if secure else "=http,https",
                     "--proto-redir", "=https" if secure else "=http,https",
                     "--connect-timeout", str(CURL_CONNECT_SECONDS),
                     "--max-time", str(CURL_DOWNLOAD_SECONDS if target else CURL_REQUEST_SECONDS),
                     "--max-filesize", str(max_bytes),
                     "--user-agent", USER_AGENT.decode("ascii"),
                     "--write-out", "%{http_code}", "--output", output]
        if self._proxy_url:
            arguments += ["--proxy", self._proxy_url]
        if body is not None:
            body_path = os.path.join(work, "request")
            with open(body_path, "wb") as stream:
                stream.write(body)
            arguments += ["--header", "Content-Type: application/x-www-form-urlencoded", "--data-binary", "@" + body_path]
        arguments.append(url)
        # 3ds Max has no console, so Qt starts curl with CREATE_NO_WINDOW: no window flashes.
        process = QtCore.QProcess(self)

        def cleanup():
            shutil.rmtree(work, ignore_errors=True)
            if target:
                _remove(output)

        self._replies[ticket] = (process, cleanup)
        handled = [False]

        def finished(exit_code=-1, _exit_status=None):
            if handled[0]:
                return
            handled[0] = True
            # forget() already removed the ticket and cleaned up: its kill must not reach the caller (PySide2 cannot
            # always disconnect the overloaded QProcess.finished signal).
            if self._replies.pop(ticket, None) is None:
                return
            result = error = None
            try:
                written = bytes(process.readAllStandardOutput()).decode("ascii", "replace").strip()
                status = int(written[-3:]) if written[-3:].isdigit() else 0
                if exit_code != 0 or status >= 400:
                    message = bytes(process.readAllStandardError()).decode("utf-8", "replace").strip()
                    raise NetworkError(message or "curl exited with code {}".format(exit_code),
                                       status if status >= 400 else 0)
                if target:
                    if not os.path.isfile(output) or os.path.getsize(output) == 0:
                        raise NetworkError("Downloaded file is empty")
                    os.replace(output, target)
                    result = target
                else:
                    with open(output, "rb") as stream:
                        result = convert(stream.read())
                if not self.curl_mode:
                    self.curl_mode = True
                    log.info("network", "curl worked where Qt networking failed; curl is used for the rest of "
                                        "this 3ds Max session")
            except Exception as exception:  # noqa: BLE001 - reported to the caller
                error = exception
            cleanup()
            process.deleteLater()
            if self.stopped or on_done is None:
                return
            _deliver(on_done, result, error)

        def failed(process_error):
            if process_error == QtCore.QProcess.FailedToStart:
                finished(-1)

        process.finished.connect(finished)
        process.errorOccurred.connect(failed)
        log.debug("network", "curl " + url)
        process.start(self.curl, arguments)

    # --- lifetime -----------------------------------------------------------------------
    def forget(self, ticket):
        handle, cleanup = self._replies.pop(ticket, (None, None))
        if handle is None:
            return
        try:
            handle.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        if isinstance(handle, QtCore.QProcess):
            handle.kill()
            handle.waitForFinished(1000)
        else:
            handle.abort()
        if cleanup is not None:
            cleanup()
        handle.deleteLater()

    def busy(self):
        return bool(self._replies)

    def stop(self):
        """Abort everything still running; their callbacks are never called."""
        self.stopped = True
        for ticket in list(self._replies):
            self.forget(ticket)
        return True


def _deliver(on_done, result, error):
    try:
        on_done(result, error)
    except Exception as exception:  # noqa: BLE001 - one bad callback must not break the others
        log.error("network", "Callback failed: " + repr(exception))


def _remove(file_path):
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass
