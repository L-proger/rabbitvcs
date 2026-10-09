"""GTK checks. Opt in with RABBITVCS_TEST_GUI=1 on an isolated display only."""
import os
import time
import unittest
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"gi\..*")

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    HAS_DISPLAY = os.environ.get('RABBITVCS_TEST_GUI') == '1' and Gtk.init_check()[0]
except ImportError:
    HAS_DISPLAY = False

import test_externals


@unittest.skipUnless(HAS_DISPLAY, 'GTK display required')
class EditorTests(unittest.TestCase):
    run_svn = test_externals.RepositoryTests.run_svn
    setUp = test_externals.RepositoryTests.setUp

    def test_property_modes_and_cancel(self):
        from rabbitvcs.ui.dialog import Property
        value = '# keep me\n^/lib@2 vendor\n'
        dialog = Property('svn:externals', value, path=str(self.wc / 'main'))
        editor = dialog.externals_editor
        self.assertIsNotNone(editor)
        self.assertFalse(dialog.recurse.get_active())
        self.assertFalse(dialog.recurse.get_sensitive())
        self.assertEqual(editor.model[0][1], 'vendor')
        editor.raw.set_active(True)
        self.assertEqual(editor.get_text(), value)
        editor.textview.get_buffer().set_text('^/lib@3 other\n')
        editor.raw.set_active(False)
        self.assertEqual(editor.model[0][3], '3')
        GLib.idle_add(dialog.get_widget('Property').response, Gtk.ResponseType.CANCEL)
        self.assertEqual(dialog.run(), (None, None, False))

    def test_new_property_switch_and_save(self):
        from rabbitvcs.ui.dialog import Property
        dialog = Property(path=str(self.wc / 'main'))
        dialog.name.set_child_text('svn:externals')
        self.assertIsNotNone(dialog.externals_editor)
        from rabbitvcs.util.externals import External
        dialog.externals_editor.document.append(External('vendor', '^/lib', '2'))
        GLib.idle_add(dialog.get_widget('Property').response, Gtk.ResponseType.OK)
        self.assertEqual(dialog.run(), ('svn:externals', '^/lib@2 vendor\n', False))

    def test_show_log_selects_peg_and_checks_out_external(self):
        from rabbitvcs.ui.externals import ExternalDialog
        from rabbitvcs.util.externals import External
        dialog = ExternalDialog(None, str(self.wc / 'main'), External('vendor', '^/lib'))
        self.addCleanup(dialog.destroy)
        dialog.show_log()
        picker = dialog.log_window
        self.assertIsNotNone(picker)
        self.addCleanup(picker.on_cancel_clicked, None)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            if not picker.is_loading and picker.revisions_table.get_items():
                break
            time.sleep(0.01)
        rows = picker.revisions_table.get_items()
        self.assertTrue(rows, 'External history did not load')
        target = next(i for i, row in enumerate(rows) if row[0] == '2')
        picker.revisions_table.treeview.get_selection().select_path(target)
        picker.on_close_clicked(None)
        self.assertEqual(dialog.fields['peg'].get_text(), '2')
        self.assertEqual(dialog.fields['operative'].get_text(), '')
        GLib.idle_add(dialog.response, Gtk.ResponseType.OK)
        item = dialog.run()
        self.run_svn('propset', '--', 'svn:externals', item.serialize(), self.wc / 'main')
        self.run_svn('update', self.wc / 'main')
        self.assertEqual((self.wc / 'main/vendor/data').read_text(), 'first')


if __name__ == '__main__':
    unittest.main()
