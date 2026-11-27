"""Before / After comparisons in package descriptions (:::compare blocks, by the rules of maxpkg.dev's
readMarkdownCompare) and the slider that shows them. The parsing tests need nothing; the slider tests need Qt."""

import unittest

from maxpkg_runtime.domain import markdown

try:
    from maxpkg_runtime.qt_compat import QtCore, QtGui, QtWidgets, Signal
    from maxpkg_runtime.ui.details import CompareSlider
    from maxpkg_runtime.ui.theme import ThemeService
except ImportError:
    QtWidgets = None

CDN = "https://cdn.maxpkg.dev/scripts/s1/content/"


def picture(name, label=None):
    return "![{}]({}{}.webp)".format(name if label is None else label, CDN, name)


def block(*body):
    return "\n".join((":::compare",) + body + (":::",))


class CompareParsingTests(unittest.TestCase):
    def setUp(self):
        self.pictures = markdown.Pictures("https://maxpkg.dev")

    def split(self, source):
        return markdown.split_media(source, self.pictures)

    def test_one_comparison_between_text(self):
        source = "\n".join(("## What it does", "Converts a V-Ray material to clean PBR maps.",
                            block(picture("vray", "V-Ray"), picture("pbr", "PBR"),
                                  "The same material **before** and after", "the conversion."),
                            "- Bakes nine channels"))
        blocks = self.split(source)
        self.assertEqual([kind for kind, _content in blocks], ["text", "compare", "text"])
        compare = blocks[1][1]
        self.assertEqual(compare.before, ("V-Ray", CDN + "vray.webp"))
        self.assertEqual(compare.after, ("PBR", CDN + "pbr.webp"))
        self.assertEqual(compare.caption, "The same material **before** and after the conversion.")
        self.assertNotIn(":::", blocks[0][1] + blocks[2][1])
        self.assertEqual(blocks[2][1], "- Bakes nine channels")

    def test_two_comparisons(self):
        source = "\n".join((block(picture("a"), picture("b")), "Between.", block(picture("c"), picture("d"), "Two")))
        blocks = self.split(source)
        self.assertEqual([kind for kind, _content in blocks], ["compare", "text", "compare"])
        self.assertEqual(blocks[0][1].caption, "")
        self.assertEqual(blocks[2][1].after[1], CDN + "d.webp")

    def test_inside_a_code_fence_it_stays_text(self):
        source = "\n".join(("```", block(picture("a"), picture("b")), "```"))
        blocks = self.split(source)
        self.assertEqual(blocks, [("text", source)])
        self.assertIn(":::compare", markdown.to_html(blocks[0][1]))

    def test_empty_labels_are_before_and_after(self):
        compare = self.split(block(picture("a", ""), picture("b", "")))[0][1]
        self.assertEqual((compare.before[0], compare.after[0]), ("Before", "After"))

    def test_a_third_picture_makes_it_text(self):
        source = block(picture("a"), picture("b"), picture("c"))
        blocks = self.split(source)
        self.assertNotIn("compare", [kind for kind, _content in blocks])
        self.assertIn(("images", [("a", CDN + "a.webp"), ("b", CDN + "b.webp"), ("c", CDN + "c.webp")]), blocks)
        self.assertTrue(any(kind == "text" and ":::compare" in content for kind, content in blocks))

    def test_not_a_picture_first_makes_it_text(self):
        blocks = self.split(block("Just words", picture("b")))
        self.assertEqual(blocks[0], ("text", ":::compare\nJust words"))

    def test_without_a_closing_line_or_with_a_blank_line_it_is_text(self):
        self.assertNotIn("compare", [kind for kind, _ in self.split(":::compare\n" + picture("a") + "\n" + picture("b"))])
        source = ":::compare\n" + picture("a") + "\n\n" + picture("b") + "\n:::"
        self.assertNotIn("compare", [kind for kind, _ in self.split(source)])
        far = ":::compare\n" + picture("a") + "\n" + picture("b") + "\n" + "words\n" * 40 + ":::"
        self.assertNotIn("compare", [kind for kind, _ in self.split(far)])

    def test_addresses_follow_the_picture_rules(self):
        compare = self.split(block("![x](/media/before.png 'title')", "![y](<https://example.test/after.png>)"))[0][1]
        self.assertEqual(compare.before, ("x", "https://maxpkg.dev/media/before.png"))  # site-relative
        self.assertEqual(compare.after, ("y", ""))  # another host: never loaded, its label shows
        self.assertEqual(self.pictures.items, [])  # not lightbox pictures: a click moves the divider

    def test_spaces_around_the_lines(self):
        compare = self.split("  :::compare  \n  " + picture("a") + "  \n" + picture("b") + "\n  :::  ")[0][1]
        self.assertEqual(compare.before[1], CDN + "a.webp")


class FeatureFieldTests(unittest.TestCase):
    def test_the_details_request_says_the_manager_shows_comparisons(self):
        from maxpkg_runtime.domain import api
        request = api.details_request("p", 2027, "2.1.8")
        self.assertIn(("features", "compare"), request.fields)
        self.assertIn(b"features=compare", request.body())
        # packages/resolve returns no description, so it needs no features
        self.assertNotIn("features", dict(api.resolve_request("p", 2027, "2.1.8").fields))


@unittest.skipIf(QtWidgets is None, "Qt is not available")
class CompareSliderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["maxpkg-tests"])
        from pathlib import Path
        cls.themes = ThemeService(Path(__file__).resolve().parents[2])

    def make(self, width=400, failed=()):
        class FakeImages(QtCore.QObject):
            """The image cache: pictures by url, and which ones failed."""
            ready = Signal(str)

            def __init__(self, pictures, broken):
                QtCore.QObject.__init__(self)
                self.pictures, self.broken = pictures, set(broken)

            def get(self, url):
                return self.pictures.get(url)

            def failed(self, url):
                return url in self.broken

        before = QtGui.QPixmap(800, 400)
        before.fill(QtGui.QColor("#ff0000"))
        after = QtGui.QPixmap(800, 400)
        after.fill(QtGui.QColor("#0000ff"))
        images = FakeImages({"b": before, "a": after}, failed)
        compare = markdown.Compare(("Before", "b"), ("After", "a"), "")
        slider = CompareSlider(compare, images, self.themes)
        slider.resize(width, slider.heightForWidth(width))
        self.addCleanup(slider.deleteLater)
        return slider

    def frame(self, slider):
        image = QtGui.QImage(slider.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        slider.render(image, QtCore.QPoint(), QtGui.QRegion(), QtWidgets.QWidget.DrawChildren)
        return image

    def press(self, slider, x, kind=None):
        point = QtCore.QPointF(x, slider.height() / 2.0)
        event = QtGui.QMouseEvent(kind or QtCore.QEvent.MouseButtonPress, point, slider.mapToGlobal(point.toPoint()),
                                  QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(slider, event)

    def key(self, slider, key):
        QtWidgets.QApplication.sendEvent(slider, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, key, QtCore.Qt.NoModifier))

    def test_the_before_picture_sets_the_size_and_is_never_enlarged(self):
        self.assertEqual(self.make().heightForWidth(400), 200)  # 2:1, at the description width
        self.assertEqual(self.make().heightForWidth(1600), 400)  # its own size, centred
        self.assertEqual(self.make().picture_rect(1600), QtCore.QRectF(400, 0, 800, 400))

    def test_before_left_of_the_divider_after_right_of_it(self):
        slider = self.make()
        self.assertEqual(slider.position, 0.5)
        image = self.frame(slider)
        self.assertGreater(image.pixelColor(100, 150).red(), 200)  # Before
        self.assertGreater(image.pixelColor(300, 150).blue(), 200)  # After
        self.assertGreater(image.pixelColor(200, 20).green(), 200)  # the white divider

    def test_press_and_drag_move_the_divider(self):
        slider = self.make()
        self.press(slider, 100)
        self.assertAlmostEqual(slider.position, 0.25)
        self.press(slider, 300, QtCore.QEvent.MouseMove)
        self.assertAlmostEqual(slider.position, 0.75)
        self.press(slider, 900, QtCore.QEvent.MouseMove)
        self.assertEqual(slider.position, 1.0)

    def test_keys_move_the_divider(self):
        slider = self.make()
        self.key(slider, QtCore.Qt.Key_Right)
        self.assertAlmostEqual(slider.position, 0.55)
        self.key(slider, QtCore.Qt.Key_Left)
        self.key(slider, QtCore.Qt.Key_Left)
        self.assertAlmostEqual(slider.position, 0.45)
        self.key(slider, QtCore.Qt.Key_Home)
        self.assertEqual(slider.position, 0.0)
        self.key(slider, QtCore.Qt.Key_End)
        self.assertEqual(slider.position, 1.0)

    def test_the_wheel_scrolls_the_page(self):
        slider = self.make()
        event = QtGui.QWheelEvent(QtCore.QPointF(50, 50), QtCore.QPointF(50, 50), QtCore.QPoint(), QtCore.QPoint(0, -120),
                                  QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
        QtWidgets.QApplication.sendEvent(slider, event)
        self.assertFalse(event.isAccepted())  # handed on to the scrolling page

    def test_a_badge_hides_while_the_divider_covers_it(self):
        slider = self.make()
        before_badge, after_badge = slider.badge_rects()
        image = self.frame(slider)
        self.assertLess(image.pixelColor(int(before_badge.left()) + 3, int(before_badge.center().y())).red(), 150)
        self.assertLess(image.pixelColor(int(after_badge.right()) - 3, int(after_badge.center().y())).blue(), 150)
        slider.set_position(0.02)  # the After picture covers the Before badge
        image = self.frame(slider)
        self.assertGreater(image.pixelColor(int(before_badge.left()) + 3, int(before_badge.center().y())).blue(), 200)

    def test_a_picture_that_fails_shows_its_label(self):
        slider = self.make(failed=("a",))
        slider.images.pictures.pop("a")
        image = self.frame(slider)
        self.assertLess(image.pixelColor(300, 150).blue(), 200)  # no After picture, the label in its place


if __name__ == "__main__":
    unittest.main()
