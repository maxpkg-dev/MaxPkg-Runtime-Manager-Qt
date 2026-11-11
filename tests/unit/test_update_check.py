"""Pure tests for domain/update_check.py: the one message of Check Updates. Run with tests/run_unit.py."""

import unittest

from maxpkg_runtime.domain import update_check as uc

ONE = [("Scatter Tool", "1.0.0", "1.1.0")]
FIVE = [("Tool " + letter, "1.0", "2.0") for letter in "ABCDE"]


def packages(status, pending=()):
    return uc.PackagesResult(status, pending)


def manager(status, version=""):
    return uc.ManagerResult(status, version)


class EverythingFineTests(unittest.TestCase):
    def test_both_current(self):
        notice = uc.summarize(packages(uc.PACKAGES_CHECKED), manager(uc.MANAGER_CURRENT, "2.1.1"))
        self.assertEqual(notice.text, "Everything is up to date.\n"
                                      "All packages and Package Manager 2.1.1 are the latest versions.")
        self.assertEqual((notice.kind, notice.actions), ("success", []))

    def test_no_packages_installed(self):
        notice = uc.summarize(packages(uc.PACKAGES_NONE), manager(uc.MANAGER_CURRENT, "2.1.1"))
        self.assertEqual(notice.text, "Package Manager 2.1.1 is up to date.\nNo installed packages to check.")
        self.assertEqual(notice.kind, "success")

    def test_a_running_self_update_leaves_the_package_wording_unchanged(self):
        self.assertEqual(uc.summarize(packages(uc.PACKAGES_CHECKED), manager(uc.MANAGER_SKIPPED)).text,
                         "All packages are up to date.")
        notice = uc.summarize(packages(uc.PACKAGES_NONE), manager(uc.MANAGER_SKIPPED))
        self.assertEqual((notice.text, notice.kind), ("No installed packages to check.", "info"))


class PackageUpdateTests(unittest.TestCase):
    def test_one_update_with_the_manager_current(self):
        notice = uc.summarize(packages(uc.PACKAGES_CHECKED, ONE), manager(uc.MANAGER_CURRENT, "2.1.1"))
        self.assertEqual(notice.text, "An update is available.\nScatter Tool 1.0.0 → 1.1.0\n"
                                      "Package Manager 2.1.1 is up to date.")
        self.assertEqual((notice.kind, notice.actions), ("info", [uc.UPDATE]))

    def test_many_updates_name_three(self):
        notice = uc.summarize(packages(uc.PACKAGES_CHECKED, FIVE), manager(uc.MANAGER_SKIPPED))
        self.assertEqual(notice.text, "5 updates are available.\nTool A, Tool B, Tool C and 2 more")
        self.assertEqual(notice.actions, [uc.UPDATE_ALL])

    def test_failed_manager_check_does_not_hide_package_updates(self):
        notice = uc.summarize(packages(uc.PACKAGES_CHECKED, ONE), manager(uc.MANAGER_FAILED))
        self.assertTrue(notice.text.startswith("An update is available.\nScatter Tool 1.0.0 → 1.1.0\n"))
        self.assertIn("The Package Manager update check failed.", notice.text)
        self.assertEqual(notice.actions, [uc.UPDATE, uc.RETRY])  # the update stays the main button

    def test_manager_waiting_for_an_operation_is_named_under_the_offer(self):
        notice = uc.summarize(packages(uc.PACKAGES_CHECKED, FIVE[:2]), manager(uc.MANAGER_WAIT, "2.1.2"))
        self.assertEqual(notice.text, "2 updates are available.\nTool A, Tool B\n"
                                      "Package Manager 2.1.2 will be installed when the current package operation ends.")

    def test_source_checkout_is_named_under_the_offer(self):
        notice = uc.summarize(packages(uc.PACKAGES_CHECKED, ONE), manager(uc.MANAGER_SOURCE, "2.1.2"))
        self.assertIn("Package Manager 2.1.2 is available: this copy runs from a source folder", notice.text)


class ManagerUpdateTests(unittest.TestCase):
    def test_installing_now_comes_first_and_offers_nothing(self):
        notice = uc.summarize(packages(uc.PACKAGES_CHECKED, ONE), manager(uc.MANAGER_INSTALL, "2.1.2"))
        self.assertEqual(notice.text, "Package Manager 2.1.2 is available.\nInstalling it now.\n"
                                      "An update for Scatter Tool is available too.")
        self.assertEqual((notice.kind, notice.actions), ("info", []))  # it restarts in a moment

    def test_installing_now_with_every_package_result(self):
        cases = ((packages(uc.PACKAGES_CHECKED), "All packages are up to date."),
                 (packages(uc.PACKAGES_CHECKED, FIVE), "5 package updates are available too."),
                 (packages(uc.PACKAGES_FAILED), "The package update check failed."))
        for result, line in cases:
            notice = uc.summarize(result, manager(uc.MANAGER_INSTALL, "2.1.2"))
            self.assertEqual(notice.text, "Package Manager 2.1.2 is available.\nInstalling it now.\n" + line)
        self.assertEqual(uc.summarize(packages(uc.PACKAGES_NONE), manager(uc.MANAGER_INSTALL, "2.1.2")).text,
                         "Package Manager 2.1.2 is available.\nInstalling it now.")

    def test_waiting_for_a_package_operation(self):
        notice = uc.summarize(packages(uc.PACKAGES_CHECKED), manager(uc.MANAGER_WAIT, "2.1.2"))
        self.assertEqual(notice.text, "Package Manager 2.1.2 is available.\n"
                                      "It will be installed when the current package operation ends.\n"
                                      "All packages are up to date.")
        self.assertEqual((notice.kind, notice.actions), ("info", []))

    def test_source_checkout_only_reports(self):
        notice = uc.summarize(packages(uc.PACKAGES_NONE), manager(uc.MANAGER_SOURCE, "2.1.2"))
        self.assertEqual(notice.text, "Package Manager 2.1.2 is available.\n"
                                      "This copy runs from a source folder: update it with git.")

    def test_failed_package_check_under_manager_news_offers_try_again(self):
        notice = uc.summarize(packages(uc.PACKAGES_FAILED), manager(uc.MANAGER_SOURCE, "2.1.2"))
        self.assertIn("The package update check failed.", notice.text)
        self.assertEqual(notice.actions, [uc.RETRY])


class FailureTests(unittest.TestCase):
    def test_package_check_failed_manager_current(self):
        notice = uc.summarize(packages(uc.PACKAGES_FAILED), manager(uc.MANAGER_CURRENT, "2.1.1"))
        self.assertEqual(notice.text, "The package update check failed.\nThe previous result is still available.\n"
                                      "Package Manager 2.1.1 is up to date.")
        self.assertEqual((notice.kind, notice.actions), ("error", [uc.RETRY]))

    def test_manager_check_failed_packages_current(self):
        notice = uc.summarize(packages(uc.PACKAGES_CHECKED), manager(uc.MANAGER_FAILED))
        self.assertEqual(notice.text, "The Package Manager update check failed.\n"
                                      "The MaxPkg release list could not be read.\nAll packages are up to date.")
        self.assertEqual((notice.kind, notice.actions), ("error", [uc.RETRY]))

    def test_manager_check_failed_without_packages_keeps_the_old_wording(self):
        notice = uc.summarize(packages(uc.PACKAGES_NONE), manager(uc.MANAGER_FAILED))
        self.assertEqual(notice.text, "The Package Manager update check failed.\n"
                                      "The MaxPkg release list could not be read.")

    def test_both_failed(self):
        notice = uc.summarize(packages(uc.PACKAGES_FAILED), manager(uc.MANAGER_FAILED))
        self.assertEqual(notice.text, "The update check failed.\nNeither the packages nor the Package Manager could be "
                                      "checked.\nThe previous result is still available.")
        self.assertEqual((notice.kind, notice.actions), ("error", [uc.RETRY]))

    def test_package_failure_alone_keeps_the_old_wording(self):
        notice = uc.summarize(packages(uc.PACKAGES_FAILED), manager(uc.MANAGER_SKIPPED))
        self.assertEqual(notice.text, "The package update check failed.\nThe previous result is still available.")


class ManagerAloneTests(unittest.TestCase):
    """Check Manager Updates: the packages were not asked, so nothing is said about them."""

    def test_current(self):
        notice = uc.summarize(packages(uc.PACKAGES_SKIPPED), manager(uc.MANAGER_CURRENT, "2.1.1"))
        self.assertEqual((notice.text, notice.kind, notice.actions), ("Package Manager 2.1.1 is up to date.", "success",
                                                                      []))

    def test_news_without_a_package_line(self):
        expected = {uc.MANAGER_INSTALL: "Package Manager 2.1.2 is available.\nInstalling it now.",
                    uc.MANAGER_WAIT: "Package Manager 2.1.2 is available.\n"
                                     "It will be installed when the current package operation ends.",
                    uc.MANAGER_SOURCE: "Package Manager 2.1.2 is available.\n"
                                       "This copy runs from a source folder: update it with git."}
        for status, text in expected.items():
            notice = uc.summarize(packages(uc.PACKAGES_SKIPPED), manager(status, "2.1.2"))
            self.assertEqual((notice.text, notice.kind, notice.actions), (text, "info", []), status)

    def test_failed(self):
        notice = uc.summarize(packages(uc.PACKAGES_SKIPPED), manager(uc.MANAGER_FAILED))
        self.assertEqual(notice.text, "The Package Manager update check failed.\n"
                                      "The MaxPkg release list could not be read.")
        self.assertEqual((notice.kind, notice.actions), ("error", [uc.RETRY]))


class UpdatedNoticeTests(unittest.TestCase):
    def test_plain(self):
        notice = uc.updated_notice("2.1.2", [])
        self.assertEqual((notice.text, notice.kind, notice.actions), ("Package Manager updated to 2.1.2.", "success",
                                                                      []))

    def test_with_package_updates(self):
        notice = uc.updated_notice("2.1.2", ONE)
        self.assertEqual(notice.text, "Package Manager updated to 2.1.2.\n"
                                      "An update is available for Scatter Tool: 1.0.0 → 1.1.0.")
        self.assertEqual(notice.actions, [uc.UPDATE])
        notice = uc.updated_notice("2.1.2", FIVE)
        self.assertEqual(notice.text, "Package Manager updated to 2.1.2.\n"
                                      "5 package updates are available: Tool A, Tool B, Tool C and 2 more.")
        self.assertEqual(notice.actions, [uc.UPDATE_ALL])


if __name__ == "__main__":
    unittest.main()
