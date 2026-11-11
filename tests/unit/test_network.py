"""Requests follow redirects the way Qt reads them: GitHub serves release files through a 302. Needs Qt; skipped where
there is none."""

import unittest

try:
    from maxpkg_runtime.qt_compat import QtCore, QtWidgets
    from maxpkg_runtime.services import network
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, "Qt is not available")
class RedirectPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["maxpkg-tests"])

    def test_requests_follow_redirects_that_are_no_less_safe(self):
        service = network.NetworkService()
        self.addCleanup(service.deleteLater)
        service._proxy_ready = True  # no proxy lookup in a test
        request = service._request("https://github.com/maxpkg-dev/MaxPkg-Runtime-Manager-Qt/releases/download/v1/file")
        policy = request.attribute(network.QtNetwork.QNetworkRequest.RedirectPolicyAttribute)
        self.assertIsInstance(policy, int)  # an enum object here is read as ManualRedirectPolicy
        self.assertEqual(policy, network._enum_number(network.QtNetwork.QNetworkRequest.NoLessSafeRedirectPolicy))
        self.assertNotEqual(policy, network._enum_number(network.QtNetwork.QNetworkRequest.ManualRedirectPolicy))


if __name__ == "__main__":
    unittest.main()
