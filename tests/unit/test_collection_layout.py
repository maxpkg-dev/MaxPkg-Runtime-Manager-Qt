"""MaxPkg.installLayout: a favorite collection arranged as a toolbar on maxpkg.dev. The layout string is read safely,
the toolbar takes the collection's order and dividers next to the user's own buttons, and the Runtime installs only
what is missing before it arranges the toolbar. The domain tests need nothing; the Runtime tests need Qt."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from maxpkg_runtime.domain.packages import DIVIDER, arrange_collection, split_layout

try:
    from maxpkg_runtime.qt_compat import QtCore
    from maxpkg_runtime.domain.packages import Package
    from maxpkg_runtime.services import max_api
    from maxpkg_runtime.services import runtime as runtime_module
except ImportError:
    QtCore = None

ROOT = Path(__file__).resolve().parents[2]
G1 = "11111111-1111-4111-8111-111111111111"
G2 = "22222222-2222-4222-8222-222222222222"
G3 = "33333333-3333-4333-8333-333333333333"
G4 = "44444444-4444-4444-8444-444444444444"
U1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
U2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
D = DIVIDER


def shown_except(*hidden):
    return lambda guid: guid not in hidden


class SplitLayoutTests(unittest.TestCase):
    def test_reads_the_site_string(self):
        text = "divider;{};{};divider;{}".format(G1, G2, G3)
        self.assertEqual(split_layout(text), [D, G1, G2, D, G3])

    def test_ignores_what_is_neither_a_guid_nor_a_divider(self):
        text = "foo;{};;DIVIDER;divider; {} ;divider;12345;{};divider".format(G1, G2, G1)
        self.assertEqual(split_layout(text), [G1, D, G2])

    def test_reads_a_maxscript_array_too(self):
        self.assertEqual(split_layout('#("{}", "divider", "{}")'.format(G1, G2)), [G1, D, G2])

    def test_has_limits(self):
        many = ";".join("{:08x}-0000-4000-8000-000000000000".format(index) + ";divider" for index in range(300))
        entries = split_layout(many)
        self.assertEqual(sum(1 for entry in entries if entry != D), 200)
        self.assertLessEqual(sum(1 for entry in entries if entry == D), 50)
        self.assertEqual(split_layout(""), [])
        self.assertEqual(split_layout("divider;divider"), [])


class ArrangeCollectionTests(unittest.TestCase):
    def test_a_toolbar_with_no_other_buttons_takes_the_layout_as_it_is(self):
        order = [D, G3, G1, G2]  # the divider after the maxpkg button, then the packages in another order
        self.assertEqual(arrange_collection(order, [D, G1, G2, D, G3], shown_except()), [D, G1, G2, D, G3])
        self.assertEqual(arrange_collection(order, [G2, G1, G3], shown_except()), [G2, G1, G3])

    def test_the_users_buttons_stay_and_the_collection_follows_them(self):
        order = [D, U1, G2, U2, G1, G3]
        arranged = arrange_collection(order, [D, G1, G2, D, G3], shown_except())
        self.assertEqual(arranged, [D, U1, U2, D, G1, G2, D, G3])
        self.assertEqual(arrange_collection(arranged, [D, G1, G2, D, G3], shown_except()), arranged)  # again: the same

    def test_a_new_order_from_the_site_replaces_the_old_one(self):
        first = arrange_collection([D, U1, G1, G2, G3], [G1, D, G2, G3], shown_except())
        self.assertEqual(first, [D, U1, D, G1, D, G2, G3])
        self.assertEqual(arrange_collection(first, [G3, G2, D, G1], shown_except()), [D, U1, D, G3, G2, D, G1])

    def test_missing_and_hidden_packages_leave_no_empty_dividers(self):
        order = [U1, G1, G3, G4]  # G2 did not install; G3 has no toolbar button
        arranged = arrange_collection(order, [G1, D, G2, D, G3, D, G4], shown_except(G3))
        self.assertEqual(arranged, [U1, D, G1, D, G4, G3])

    def test_a_divider_left_alone_by_the_collection_goes(self):
        self.assertEqual(arrange_collection([D, U1, D, G1], [G1], shown_except()), [D, U1, D, G1])
        self.assertEqual(arrange_collection([D, U1, D, G1, D], [G1], shown_except()), [D, U1, D, G1])

    def test_nothing_to_show_adds_no_divider(self):
        self.assertEqual(arrange_collection([U1, G3], [G3], shown_except(G3)), [U1, G3])

    def test_matches_guids_in_any_case(self):
        self.assertEqual(arrange_collection([G2, G1], [G1.upper(), G2.upper()], shown_except()), [G1, G2])


def _from_this_repository():
    """run_unit.py imports this repository's modules; never patch the ones of a running Package Manager."""
    module = os.path.normcase(str(Path(runtime_module.__file__).resolve()))
    return module.startswith(os.path.normcase(str(ROOT)) + os.sep)


@unittest.skipIf(QtCore is None, "Qt is not available")
class RequestLayoutTests(unittest.TestCase):
    def setUp(self):
        if not _from_this_repository():
            self.skipTest("the maxpkg_runtime modules are not this repository's (run tests/run_unit.py)")
        self.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication(["maxpkg-tests"])
        self.base = Path(tempfile.mkdtemp(prefix="maxpkg-layout-"))
        temp = self.base / "max-temp"
        temp.mkdir()
        originals = (max_api.get_dir, max_api.max_year)
        max_api.get_dir = lambda name: str(temp) if name == "temp" else ""
        max_api.max_year = lambda: 2027
        self.addCleanup(lambda: (setattr(max_api, "get_dir", originals[0]), setattr(max_api, "max_year", originals[1])))
        self.runtime = runtime_module.Runtime(self.base, "2.1.4", "stable")
        self.runtime.network.stop()
        self.runtime.packages = [Package(guid=U1, name="Mine", version="1.0.0"),
                                 Package(guid=G1, name="One", version="1.0.0")]
        self.runtime.settings.toolbar_order = [D, U1, G1]
        self.messages = []
        self.runtime.notify.connect(lambda text, kind, actions: self.messages.append((text, kind)))
        self.installs = []  # [reference, on_done]
        self.runtime.install = self.fake_install

    def tearDown(self):
        self.runtime.stop()
        self.runtime.deleteLater()
        shutil.rmtree(str(self.base), ignore_errors=True)

    def fake_install(self, reference, on_done=None, **_options):
        self.runtime._begin("Installing package...")
        self.installs.append([reference, on_done])
        return True

    def finish_install(self, ok=True):
        """The running install ends; the next queued one starts, as the Runtime's timer would start it."""
        reference, on_done = self.installs[-1]
        if ok:
            self.runtime.packages.append(Package(guid=reference, name=reference[:2], version="1.0.0"))
        self.runtime.last_install = (reference[:2], ok, "")
        self.runtime._finish()
        on_done(ok)
        self.runtime._next_queued()

    def test_installs_only_what_is_missing_then_arranges(self):
        self.assertEqual(self.runtime.request_layout([D, G2, G1, D, G3]), 2)
        self.assertEqual([install[0] for install in self.installs], [G2])
        self.assertEqual(self.runtime.install_queue, [G3])
        self.assertEqual(self.runtime.settings.toolbar_order, [D, U1, G1])  # not before the queue is done
        self.finish_install()
        self.assertEqual([install[0] for install in self.installs], [G2, G3])
        self.finish_install()
        self.assertEqual(self.runtime.settings.toolbar_order, [D, U1, D, G2, G1, D, G3])
        self.assertIn(("All 2 packages were installed.", "success"), self.messages)

    def test_a_package_that_failed_is_left_out(self):
        self.runtime.request_layout([G2, D, G3, G1])
        self.finish_install(ok=False)
        self.finish_install()
        self.assertEqual(self.runtime.settings.toolbar_order, [D, U1, D, G3, G1])

    def test_an_installed_collection_is_arranged_at_once(self):
        self.runtime.packages.append(Package(guid=G2, name="Two", version="1.0.0"))
        self.runtime.settings.set_hidden(G2, True)
        self.assertEqual(self.runtime.request_layout([G2, D, G1]), 0)
        self.assertEqual(self.installs, [])
        self.assertEqual(self.runtime.settings.toolbar_order, [D, U1, D, G2, D, G1])
        self.assertFalse(self.runtime.settings.is_hidden(G2))  # the collection asks for its button
        self.assertTrue(any("already installed" in text for text, _kind in self.messages))

    def test_a_locked_toolbar_keeps_its_order(self):
        self.runtime.settings.toolbar_locked = True
        self.runtime.request_layout([G1, D])
        self.assertEqual(self.runtime.settings.toolbar_order, [D, U1, G1])
        self.assertTrue(any("locked" in text for text, _kind in self.messages))


if __name__ == "__main__":
    unittest.main()
