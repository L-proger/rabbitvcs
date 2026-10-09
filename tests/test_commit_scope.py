"""Commit selection across real SVN external repository boundaries."""
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pysvn

from rabbitvcs.util.commit_scope import CommitScope


class WorkingCopies:
    def svn(self, *args):
        return subprocess.check_output(
            ['svn', '--non-interactive', *map(str, args)],
            stderr=subprocess.STDOUT, text=True)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = pathlib.Path(temp.name)
        self.wc = root / 'wc'
        for name in ('repo', 'other'):
            subprocess.check_call(['svnadmin', 'create', str(root / name)])
            self.svn('mkdir', (root / name).as_uri() + '/lib', '-m', 'init')
        self.svn('mkdir', (root / 'repo').as_uri() + '/main', '-m', 'main project')
        self.svn('checkout', (root / 'repo').as_uri(), self.wc)
        (self.wc / 'lib/data').write_text('base')
        (self.wc / 'main/data').write_text('base')
        self.svn('add', self.wc / 'main/data')
        self.svn('add', self.wc / 'lib/data')
        self.svn('commit', self.wc, '-m', 'add library data')
        self.svn('update', self.wc)
        self.svn('propset', 'svn:externals',
                 '^/lib same\n' + (root / 'other').as_uri() + '/lib foreign', self.wc)
        self.svn('commit', self.wc, '-m', 'externals')
        self.svn('update', self.wc)
        (self.wc / 'foreign/data').write_text('base')
        self.svn('add', self.wc / 'foreign/data')
        self.svn('commit', self.wc / 'foreign', '-m', 'add library data')
        for name in ('main', 'same', 'foreign'):
            (self.wc / name / 'data').write_text('changed')
            (self.wc / name / 'new').write_text('new')


class ScopeTests(WorkingCopies, unittest.TestCase):
    def test_repository_boundaries_and_unversioned_children(self):
        scope = CommitScope(pysvn.Client(), self.wc)
        for name, permitted in [('main', True), ('same', True), ('foreign', False)]:
            self.assertEqual(scope.permits(self.wc / name / 'data'), permitted)
            self.assertEqual(scope.permits(self.wc / name / 'new', unversioned=True), permitted)
        foreign = CommitScope(pysvn.Client(), self.wc / 'foreign')
        self.assertTrue(foreign.permits(self.wc / 'foreign/data'))
        self.assertFalse(foreign.permits(self.wc / 'main/data'))
        self.assertFalse(scope.permits(self.wc / 'nonexistent'))
        new_file = CommitScope(pysvn.Client(), self.wc / 'main/new')
        self.assertTrue(new_file.permits(self.wc / 'main/new', unversioned=True))
        (self.wc / 'main/data').unlink()
        self.assertTrue(scope.permits(self.wc / 'main/data'))

    def test_single_commit_of_same_repository_external(self):
        scope = CommitScope(pysvn.Client(), self.wc)
        paths = [self.wc / name / 'data' for name in ('main', 'same', 'foreign')]
        allowed = [path for path in paths if scope.permits(path)]
        pysvn.Client().checkin(list(map(str, allowed)), 'combined commit', recurse=False)
        self.assertEqual(self.svn('status', self.wc / 'main/data').strip(), '')
        self.assertEqual(self.svn('status', self.wc / 'same/data').strip(), '')
        self.assertTrue(self.svn('status', self.wc / 'foreign/data').startswith('M'))


@unittest.skipUnless(os.environ.get('RABBITVCS_TEST_GUI') == '1', 'GTK display required')
class CommitWindowTests(WorkingCopies, unittest.TestCase):
    def test_f5_refresh_after_external_commit_preserves_draft_and_selection(self):
        from gi.repository import Gtk, Gdk, GdkX11
        self.assertIsInstance(Gdk.Display.get_default(), GdkX11.X11Display)
        from rabbitvcs.ui.commit import SVNCommit
        with patch.object(SVNCommit, 'initialize_items'):
            window = SVNCommit([str(self.wc)], str(self.wc))
        self.addCleanup(window.close)

        def drain_events():
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

        def rows_by_path():
            return {str(row[1]): row for row in window.files_table.get_items()}

        window.load()
        drain_events()
        local_path = str(self.wc / 'main/data')
        foreign_path = str(self.wc / 'foreign/data')
        self.assertIn(foreign_path, rows_by_path())
        window.message.set_text('Keep this unfinished commit message')
        local = rows_by_path()[local_path]
        local[0] = False
        window.on_files_table_toggle_event(local, 0)

        self.svn('commit', foreign_path, '-m', 'commit external separately')
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_F5
        event.state = Gdk.ModifierType(0)
        self.assertTrue(window.get_widget('Commit').emit('key-press-event', event))
        drain_events()
        self.assertNotIn(foreign_path, rows_by_path())
        self.assertIn(local_path, rows_by_path())
        self.assertFalse(rows_by_path()[local_path][0])
        self.assertEqual(window.message.get_text(), 'Keep this unfinished commit message')

    def test_blocked_rows_selection_and_commit_submission(self):
        from gi.repository import Gtk, Gdk, GdkX11
        self.assertIsInstance(Gdk.Display.get_default(), GdkX11.X11Display)
        from rabbitvcs.ui.commit import SVNCommit
        with patch.object(SVNCommit, 'initialize_items'):
            window = SVNCommit([str(self.wc)], str(self.wc))
        self.addCleanup(window.close)
        window.load()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        rows = list(window.files_table.get_items())
        foreign = next(row for row in rows if str(row[1]) == str(self.wc / 'foreign/data'))
        local = next(row for row in rows if str(row[1]) == str(self.wc / 'main/data'))
        self.assertFalse(foreign[0])
        self.assertFalse(foreign[6])
        self.assertIn('commit separately', foreign[7])
        self.assertTrue(local[0])
        tree = window.files_table.treeview
        model = tree.get_model()
        for row in model:
            if str(row[1]) == str(self.wc / 'foreign/data'):
                for column in tree.get_columns()[:6]:
                    column.cell_set_cell_data(model, row.iter, False, False)
                    for cell in column.get_cells():
                        self.assertFalse(cell.get_property('sensitive'))
        window.on_toggle_show_all_toggled(None)
        self.assertFalse(foreign[0])
        foreign[0] = True
        window.on_files_table_toggle_event(foreign, 0)
        self.assertFalse(foreign[0])
        # Committing from inside the external must still be possible.
        with patch.object(SVNCommit, 'initialize_items'):
            external_window = SVNCommit([str(self.wc / 'foreign')], str(self.wc / 'foreign'))
        self.addCleanup(external_window.close)
        external_window.load()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        external_rows = list(external_window.files_table.get_items())
        self.assertTrue(any(row[0] and row[6] for row in external_rows))
        # Defence even if a stale or programmatic selection sets the checkbox.
        foreign[0] = True
        with patch('rabbitvcs.ui.action.SVNAction') as action:
            window.on_ok_clicked(None)
        calls = action.return_value.append.call_args_list
        submitted = next(call.args[1] for call in calls if call.args[0] == window.do_commit)
        self.assertNotIn(str(self.wc / 'foreign/data'), list(map(str, submitted)))
        self.assertIn(str(self.wc / 'main/data'), list(map(str, submitted)))


if __name__ == '__main__':
    unittest.main()
