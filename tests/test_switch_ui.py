"""Repository selection in Switch; GUI tests require XWayland."""
import os
import time
import unittest
from unittest.mock import patch

import test_externals


@unittest.skipUnless(os.environ.get('RABBITVCS_TEST_GUI') == '1', 'GTK display required')
class SwitchBrowserTests(unittest.TestCase):
    setUp = test_externals.RepositoryTests.setUp
    run_svn = test_externals.RepositoryTests.run_svn

    def wait_for_listing(self, picker):
        from gi.repository import Gtk
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            if picker.items:
                return
            time.sleep(0.01)
        self.fail('Repository listing did not load')

    def choose(self, picker, ending):
        tree = picker.list_table.treeview
        for row in tree.get_model():
            if str(row[0]).endswith(ending):
                tree.get_selection().select_iter(row.iter)
                return
        self.fail('Missing directory: ' + ending)

    def test_browse_select_cancel_and_revision(self):
        from gi.repository import Gdk, GdkX11
        self.assertIsInstance(Gdk.Display.get_default(), GdkX11.X11Display)
        from rabbitvcs.ui.switch import SVNSwitch
        self.run_svn('copy', self.url + '/main', self.url + '/release one', '-m', 'tag')
        window = SVNSwitch(str(self.wc / 'main'))
        self.addCleanup(window.close)
        original = window.repositories.get_active_text()
        window.get_widget('repo_browser').clicked()
        picker = window.repo_browser
        self.addCleanup(picker.close)
        self.wait_for_listing(picker)
        self.choose(picker, '..')
        picker.on_row_activated(None, None, None)
        self.wait_for_listing(picker)
        self.choose(picker, '/release one')
        picker.on_close_clicked(None)
        self.assertEqual(window.repositories.get_active_text(), self.url + '/release one')
        self.assertTrue(picker.closed)
        # Selection only edits the URL; it never switches the working copy.
        self.assertEqual(window.svn.get_repo_url(str(self.wc / 'main')), original)
        window.get_widget('repo_browser').clicked()
        picker = window.repo_browser
        self.wait_for_listing(picker)
        picker.on_cancel_clicked(None)
        self.assertEqual(window.repositories.get_active_text(), self.url + '/release one')
        window.repositories.set_child_text(self.url + '/lib')
        window.revision_selector.set_kind_number(2)
        window.get_widget('repo_browser').clicked()
        picker = window.repo_browser
        self.addCleanup(picker.close)
        self.wait_for_listing(picker)
        self.assertEqual(int(picker.browse_revision.value), 2)
        self.choose(picker, '/data')
        self.assertFalse(picker.get_widget('close').get_sensitive())
        picker.on_close_clicked(None)
        self.assertFalse(picker.closed)
        picker.list_table.treeview.get_selection().unselect_all()
        picker.on_close_clicked(None)
        self.assertTrue(picker.closed)
        self.assertEqual(int(window.revision_selector.get_revision_object().value), 2)
        # Verify the existing Switch command gets the selected URL and revision.
        with patch('rabbitvcs.ui.action.SVNAction') as action:
            window.on_ok_clicked(None)
        calls = action.return_value.append.call_args_list
        switch = next(call for call in calls if call.args[0] == window.svn.switch)
        self.assertEqual(switch.args[2], self.url + '/lib')
        self.assertEqual(int(switch.kwargs['revision'].value), 2)
