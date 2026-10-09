"""Run with: XDG_CONFIG_HOME=/tmp/rabbitvcs-tests python3 -m unittest discover -s tests"""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from rabbitvcs.util.externals import External, ExternalsDocument, parse_line, resolve_url


class ExternalsTests(unittest.TestCase):
    def test_revision_forms(self):
        for flag in ('-r42', '-r 42'):
            self.assertEqual(parse_line(flag + ' ^/lib@51 "vendor/lib one"'),
                             External('vendor/lib one', '^/lib', '51', '42'))
        self.assertEqual(parse_line('^/lib@42 lib'), External('lib', '^/lib', '42'))
        self.assertEqual(parse_line('^/lib lib'), External('lib', '^/lib'))

    def test_legacy_revisions_and_literal_at(self):
        item = parse_line('lib -r42 https://host/repo/lib@name')
        self.assertEqual(item, External('lib', 'https://host/repo/lib@name', '42', '42'))
        self.assertEqual(parse_line(item.serialize()), item)

    def test_roundtrip_quotes_and_at(self):
        for item in [External('folder with spaces', '^/lib', '7'),
                     External('lib', 'svn+ssh://user@host/repo/lib'),
                     External('lib', '^/lib@name'),
                     External("it's a lib", '^/lib'), External('lib', '^/lib', '0', '0')]:
            self.assertEqual(parse_line(item.serialize()), item)
        self.assertEqual(parse_line('svn+ssh://user@host/repo/lib lib').url,
                         'svn+ssh://user@host/repo/lib')

    def test_lossless_document_and_opaque_dates(self):
        source = '# keep comment\r\n\r\n  -r 12 ^/lib@15 "local lib"\r\n^/other@{2020-01-01} other\nmalformed'
        document = ExternalsDocument(source)
        self.assertEqual(document.text(), source)
        self.assertEqual(len(list(document.entries())), 3)
        document.replace(2, External('local lib', '^/lib', '16', '12'))
        self.assertTrue(document.text().startswith('# keep comment\r\n\r\n-r12 ^/lib@16 "local lib"\r\n'))
        self.assertTrue(document.text().endswith('^/other@{2020-01-01} other\nmalformed'))

    def test_add_without_final_newline(self):
        document = ExternalsDocument('# comment')
        document.append(External('lib', '^/lib'))
        self.assertEqual(document.text(), '# comment\n^/lib lib\n')

    def test_invalid_fields(self):
        for item in [External('../escape', '^/lib'), External('/absolute', '^/lib'),
                     External('.', '^/lib'), External('lib', 'garbage'),
                     External('lib', '^/lib', '-1'), External('lib', '^/lib\n^/other'),
                     External('lib', '^/lib', '1:2')]:
            with self.assertRaises(ValueError):
                item.serialize()

    def test_relative_urls(self):
        owner = 'svn+ssh://user@host/repos/project/trunk/sub'
        root = 'svn+ssh://user@host/repos/project'
        for url, expected in [
            ('^/libs', root + '/libs'),
            ('^/../other/lib', 'svn+ssh://user@host/repos/other/lib'),
            ('../lib', 'svn+ssh://user@host/repos/project/trunk/lib'),
            ('//other/repos/lib', 'svn+ssh://other/repos/lib'),
            ('/repos/lib', 'svn+ssh://user@host/repos/lib'),
            ('https://elsewhere/lib', 'https://elsewhere/lib'),
        ]:
            self.assertEqual(resolve_url(url, owner, root), expected)


@unittest.skipUnless(shutil.which('svn') and shutil.which('svnadmin'), 'SVN CLI required')
class RepositoryTests(unittest.TestCase):
    def run_svn(self, *args):
        return subprocess.check_output(['svn', '--non-interactive', *map(str, args)], stderr=subprocess.STDOUT, text=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = pathlib.Path(self.temp.name)
        repo = base / 'repo'
        subprocess.check_call(['svnadmin', 'create', str(repo)])
        self.url = repo.as_uri()
        self.wc = base / 'wc'
        self.run_svn('mkdir', self.url + '/main', self.url + '/lib', '-m', 'create')
        self.run_svn('checkout', self.url, self.wc)
        (self.wc / 'lib' / 'data').write_text('first')
        self.run_svn('add', self.wc / 'lib' / 'data')
        self.run_svn('commit', self.wc, '-m', 'external revision two')
        (self.wc / 'lib' / 'data').write_text('second')
        self.run_svn('commit', self.wc, '-m', 'external revision three')

    def test_peg_selects_checkout_revision_and_operative_overrides(self):
        for operative, expected in [('', 'first'), ('3', 'second')]:
            item = External('vendor lib', '^/lib', '2', operative)
            self.run_svn('propset', '--', 'svn:externals', item.serialize(), self.wc / 'main')
            self.run_svn('update', self.wc / 'main')
            self.assertEqual((self.wc / 'main/vendor lib/data').read_text(), expected)

    def test_legacy_conversion_keeps_checkout(self):
        item = parse_line('vendor -r2 ' + self.url + '/lib')
        self.run_svn('propset', '--', 'svn:externals', item.serialize(), self.wc / 'main')
        self.run_svn('update', self.wc / 'main')
        self.assertEqual((self.wc / 'main/vendor/data').read_text(), 'first')

    def test_log_for_deleted_external_uses_peg(self):
        from rabbitvcs.vcs.svn import SVN
        svn = SVN()
        self.run_svn('delete', self.url + '/lib', '-m', 'delete external at HEAD')
        peg = svn.revision('number', number=2)
        entries = svn.log(self.url + '/lib', revision_start=peg, peg_revision=peg)
        self.assertEqual([int(entry.revision.value) for entry in entries], [2, 1])
        self.assertEqual(entries[0].message, 'external revision two')


if __name__ == '__main__':
    unittest.main()
