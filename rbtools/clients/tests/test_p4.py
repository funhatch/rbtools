"""Unit tests for PerforceClient."""

from __future__ import unicode_literals

import os
import re
import time
from hashlib import md5

from rbtools.api.capabilities import Capabilities
from rbtools.clients.errors import (InvalidRevisionSpecError,
                                    TooManyRevisionsError)
from rbtools.clients.perforce import PerforceClient, P4Wrapper
from rbtools.clients.tests import SCMClientTestCase
from rbtools.testing import TestCase
from rbtools.utils.filesystem import make_tempfile


class P4WrapperTests(TestCase):
    """Unit tests for P4Wrapper."""

    def is_supported(self):
        return True

    def test_counters(self):
        """Testing P4Wrapper.counters"""
        class TestWrapper(P4Wrapper):
            def run_p4(self, cmd, *args, **kwargs):
                return [
                    'a = 1\n',
                    'b = 2\n',
                    'c = 3\n',
                ]

        p4 = TestWrapper(None)
        info = p4.counters()

        self.assertEqual(
            info,
            {
                'a': '1',
                'b': '2',
                'c': '3',
            })

    def test_info(self):
        """Testing P4Wrapper.info"""
        class TestWrapper(P4Wrapper):
            def run_p4(self, cmd, *args, **kwargs):
                return [
                    'User name: myuser\n',
                    'Client name: myclient\n',
                    'Client host: myclient.example.com\n',
                    'Client root: /path/to/client\n',
                    'Server uptime: 111:43:38\n',
                ]

        p4 = TestWrapper(None)
        info = p4.info()

        self.assertEqual(
            info,
            {
                'Client host': 'myclient.example.com',
                'Client name': 'myclient',
                'Client root': '/path/to/client',
                'Server uptime': '111:43:38',
                'User name': 'myuser',
            })


class PerforceClientTests(SCMClientTestCase):
    """Unit tests for PerforceClient."""

    scmclient_cls = PerforceClient

    class P4DiffTestWrapper(P4Wrapper):
        def __init__(self, options):
            super(
                PerforceClientTests.P4DiffTestWrapper, self).__init__(options)

            self._timestamp = time.mktime(time.gmtime(0))

        def fstat(self, depot_path, fields=[]):
            assert depot_path in self.fstat_files

            fstat_info = self.fstat_files[depot_path]

            for field in fields:
                assert field in fstat_info

            return fstat_info

        def opened(self, changenum):
            return [info for info in self.repo_files
                    if info['change'] == changenum]

        def print_file(self, depot_path, out_file):
            for info in self.repo_files:
                if depot_path == '%s#%s' % (info['depotFile'], info['rev']):
                    fp = open(out_file, 'w')
                    fp.write(info['text'])
                    fp.close()
                    return
            assert False

        def where(self, depot_path):
            assert depot_path in self.where_files

            return [{
                'path': self.where_files[depot_path],
            }]

        def change(self, changenum):
            return [{
                'Change': str(changenum),
                'Date': '2013/01/02 22:33:44',
                'User': 'joe@example.com',
                'Status': 'pending',
                'Description': 'This is a test.\n',
            }]

        def info(self):
            return {
                'Client root': '/',
            }

        def run_p4(self, *args, **kwargs):
            assert False

    def build_client(self, wrapper_cls=P4DiffTestWrapper, **kwargs):
        """Build a client for testing.

        THis will set default command line options for the client and
        server, and allow for specifying a custom Perforce wrapper class.

        Version Added:
            4.0

        Args:
            wrapper_cls (type, optional):
                The P4 wrapper class to pass to the client.

            **kwargs (dict, optional):
                Additional keyword arguments to pass to the parent method.

        Returns:
            rbtools.clients.perforce.PerforceClient:
            The client instance.
        """
        return super(PerforceClientTests, self).build_client(
            client_kwargs={
                'p4_class': wrapper_cls,
            },
            options=dict({
                'p4_client': 'myclient',
                'p4_passwd': '',
                'p4_port': 'perforce.example.com:1666',
            }, **kwargs.pop('options', {})),
            **kwargs)

    def test_scan_for_server_with_reviewboard_url(self):
        """Testing PerforceClient.scan_for_server with reviewboard.url"""
        RB_URL = 'http://reviewboard.example.com/'

        class TestWrapper(P4Wrapper):
            def counters(self):
                return {
                    'reviewboard.url': RB_URL,
                    'foo': 'bar',
                }

        client = self.build_client(wrapper_cls=TestWrapper)
        url = client.scan_for_server(None)

        self.assertEqual(url, RB_URL)

    def test_get_repository_info_with_server_address(self):
        """Testing PerforceClient.get_repository_info with server address"""
        SERVER_PATH = 'perforce.example.com:1666'

        class TestWrapper(P4Wrapper):
            def is_supported(self):
                return True

            def counters(self):
                return {}

            def info(self):
                return {
                    'Client root': os.getcwd(),
                    'Server address': SERVER_PATH,
                    'Server version': 'P4D/FREEBSD60X86_64/2012.2/525804 '
                                      '(2012/09/18)',
                }

        client = self.build_client(wrapper_cls=TestWrapper)
        info = client.get_repository_info()

        self.assertIsNotNone(info)
        self.assertEqual(info.path, SERVER_PATH)
        self.assertEqual(client.p4d_version, (2012, 2))

    def test_get_repository_info_with_broker_address(self):
        """Testing PerforceClient.get_repository_info with broker address"""
        BROKER_PATH = 'broker.example.com:1666'
        SERVER_PATH = 'perforce.example.com:1666'

        class TestWrapper(P4Wrapper):
            def is_supported(self):
                return True

            def counters(self):
                return {}

            def info(self):
                return {
                    'Client root': os.getcwd(),
                    'Broker address': BROKER_PATH,
                    'Server address': SERVER_PATH,
                    'Server version': 'P4D/FREEBSD60X86_64/2012.2/525804 '
                                      '(2012/09/18)',
                }

        client = self.build_client(wrapper_cls=TestWrapper)
        info = client.get_repository_info()

        self.assertIsNotNone(info)
        self.assertEqual(info.path, BROKER_PATH)
        self.assertEqual(client.p4d_version, (2012, 2))

    def test_get_repository_info_with_server_address_and_encrypted(self):
        """Testing PerforceClient.get_repository_info with server address
        and broker encryption"""
        SERVER_PATH = 'perforce.example.com:1666'

        class TestWrapper(P4Wrapper):
            def is_supported(self):
                return True

            def counters(self):
                return {}

            def info(self):
                return {
                    'Client root': os.getcwd(),
                    'Server address': SERVER_PATH,
                    'Server encryption': 'encrypted',
                    'Server version': 'P4D/FREEBSD60X86_64/2012.2/525804 '
                                      '(2012/09/18)',
                }

        client = self.build_client(wrapper_cls=TestWrapper)
        info = client.get_repository_info()

        self.assertIsNotNone(info)
        self.assertEqual(info.path, [
            'ssl:%s' % SERVER_PATH,
            SERVER_PATH,
        ])
        self.assertEqual(client.p4d_version, (2012, 2))

    def test_get_repository_info_with_broker_address_and_encrypted(self):
        """Testing PerforceClient.get_repository_info with broker address
        and broker encryption"""
        BROKER_PATH = 'broker.example.com:1666'
        SERVER_PATH = 'perforce.example.com:1666'

        class TestWrapper(P4Wrapper):
            def is_supported(self):
                return True

            def counters(self):
                return {}

            def info(self):
                return {
                    'Client root': os.getcwd(),
                    'Broker address': BROKER_PATH,
                    'Broker encryption': 'encrypted',
                    'Server address': SERVER_PATH,
                    'Server version': 'P4D/FREEBSD60X86_64/2012.2/525804 '
                                      '(2012/09/18)',
                }

        client = self.build_client(wrapper_cls=TestWrapper)
        info = client.get_repository_info()

        self.assertIsNotNone(info)
        self.assertEqual(info.path, [
            'ssl:%s' % BROKER_PATH,
            BROKER_PATH,
        ])
        self.assertEqual(client.p4d_version, (2012, 2))

    def test_get_repository_info_with_repository_name_counter(self):
        """Testing PerforceClient.get_repository_info with repository name
        counter
        """
        SERVER_PATH = 'perforce.example.com:1666'

        class TestWrapper(P4Wrapper):
            def is_supported(self):
                return True

            def counters(self):
                return {
                    'reviewboard.repository_name': 'myrepo',
                }

            def info(self):
                return {
                    'Client root': os.getcwd(),
                    'Server address': SERVER_PATH,
                    'Server version': 'P4D/FREEBSD60X86_64/2012.2/525804 '
                                      '(2012/09/18)',
                }

        client = self.build_client(wrapper_cls=TestWrapper)
        info = client.get_repository_info()

        self.assertIsNotNone(info)
        self.assertEqual(info.path, SERVER_PATH)
        self.assertEqual(client.p4d_version, (2012, 2))

        self.assertEqual(client.get_repository_name(), 'myrepo')

    def test_get_repository_info_outside_client_root(self):
        """Testing PerforceClient.get_repository_info outside client root"""
        SERVER_PATH = 'perforce.example.com:1666'

        class TestWrapper(P4Wrapper):
            def is_supported(self):
                return True

            def info(self):
                return {
                    'Client root': '/',
                    'Server address': SERVER_PATH,
                    'Server version': 'P4D/FREEBSD60X86_64/2012.2/525804 '
                                      '(2012/09/18)',
                }

        client = self.build_client(wrapper_cls=TestWrapper)
        info = client.get_repository_info()

        self.assertIsNone(info)

    def test_scan_for_server_with_reviewboard_url_encoded(self):
        """Testing PerforceClient.scan_for_server with encoded
        reviewboard.url.http:||
        """
        URL_KEY = 'reviewboard.url.http:||reviewboard.example.com/'
        RB_URL = 'http://reviewboard.example.com/'

        class TestWrapper(P4Wrapper):
            def counters(self):
                return {
                    URL_KEY: '1',
                    'foo': 'bar',
                }

        client = self.build_client(wrapper_cls=TestWrapper)
        url = client.scan_for_server(None)

        self.assertEqual(url, RB_URL)

    def test_diff_with_pending_changelist(self):
        """Testing PerforceClient.diff with a pending changelist"""
        client = self.build_client()
        client.p4.repo_files = [
            {
                'depotFile': '//mydepot/test/README',
                'rev': '2',
                'action': 'edit',
                'change': '12345',
                'text': 'This is a test.\n',
            },
            {
                'depotFile': '//mydepot/test/README',
                'rev': '3',
                'action': 'edit',
                'change': '',
                'text': 'This is a mess.\n',
            },
            {
                'depotFile': '//mydepot/test/COPYING',
                'rev': '1',
                'action': 'add',
                'change': '12345',
                'text': 'Copyright 2013 Joe User.\n',
            },
            {
                'depotFile': '//mydepot/test/Makefile',
                'rev': '3',
                'action': 'delete',
                'change': '12345',
                'text': 'all: all\n',
            },
        ]

        readme_file = make_tempfile()
        copying_file = make_tempfile()
        makefile_file = make_tempfile()
        client.p4.print_file('//mydepot/test/README#3', readme_file)
        client.p4.print_file('//mydepot/test/COPYING#1', copying_file)

        client.p4.where_files = {
            '//mydepot/test/README': readme_file,
            '//mydepot/test/COPYING': copying_file,
            '//mydepot/test/Makefile': makefile_file,
        }

        revisions = client.parse_revision_spec(['12345'])

        self.assertEqual(
            self._normalize_diff(client.diff(revisions)),
            {
                'changenum': '12345',
                'diff': (
                    b'--- //mydepot/test/README\t//mydepot/test/README#2\n'
                    b'+++ //mydepot/test/README\t2022-01-02 12:34:56\n'
                    b'@@ -1 +1 @@\n'
                    b'-This is a test.\n'
                    b'+This is a mess.\n'
                    b'--- //mydepot/test/COPYING\t//mydepot/test/COPYING#0\n'
                    b'+++ //mydepot/test/COPYING\t2022-01-02 12:34:56\n'
                    b'@@ -0,0 +1 @@\n'
                    b'+Copyright 2013 Joe User.\n'
                    b'--- //mydepot/test/Makefile\t//mydepot/test/Makefile#3\n'
                    b'+++ //mydepot/test/Makefile\t2022-01-02 12:34:56\n'
                    b'@@ -1 +0,0 @@\n'
                    b'-all: all\n'
                ),
            })

    def test_diff_for_submitted_changelist(self):
        """Testing PerforceClient.diff with a submitted changelist"""
        class TestWrapper(self.P4DiffTestWrapper):
            def change(self, changelist):
                return [{
                    'Change': '12345',
                    'Date': '2013/12/19 11:32:45',
                    'User': 'example',
                    'Status': 'submitted',
                    'Description': 'My change description\n',
                }]

            def filelog(self, path):
                return [
                    {
                        'change0': '12345',
                        'action0': 'edit',
                        'rev0': '3',
                        'depotFile': '//mydepot/test/README',
                    }
                ]

        client = self.build_client(wrapper_cls=TestWrapper)
        client.p4.repo_files = [
            {
                'depotFile': '//mydepot/test/README',
                'rev': '2',
                'action': 'edit',
                'change': '12345',
                'text': 'This is a test.\n',
            },
            {
                'depotFile': '//mydepot/test/README',
                'rev': '3',
                'action': 'edit',
                'change': '',
                'text': 'This is a mess.\n',
            },
        ]

        readme_file = make_tempfile()
        client.p4.print_file('//mydepot/test/README#3', readme_file)

        client.p4.where_files = {
            '//mydepot/test/README': readme_file,
        }
        client.p4.repo_files = [
            {
                'depotFile': '//mydepot/test/README',
                'rev': '2',
                'action': 'edit',
                'change': '12345',
                'text': 'This is a test.\n',
            },
            {
                'depotFile': '//mydepot/test/README',
                'rev': '3',
                'action': 'edit',
                'change': '',
                'text': 'This is a mess.\n',
            },
        ]

        revisions = client.parse_revision_spec(['12345'])

        self.assertEqual(
            self._normalize_diff(client.diff(revisions)),
            {
                'diff': (
                    b'--- //mydepot/test/README\t//mydepot/test/README#2\n'
                    b'+++ //mydepot/test/README\t2022-01-02 12:34:56\n'
                    b'@@ -1 +1 @@\n'
                    b'-This is a test.\n'
                    b'+This is a mess.\n'
                ),
            })

    def test_diff_with_moved_files_cap_on(self):
        """Testing PerforceClient.diff with moved files and capability on"""
        self._test_diff_with_moved_files(
            expected_diff=(
                b'Moved from: //mydepot/test/README\n'
                b'Moved to: //mydepot/test/README-new\n'
                b'--- //mydepot/test/README\t//mydepot/test/README#2\n'
                b'+++ //mydepot/test/README-new\t2022-01-02 12:34:56\n'
                b'@@ -1 +1 @@\n'
                b'-This is a test.\n'
                b'+This is a mess.\n'
                b'==== //mydepot/test/COPYING#2 ==MV== '
                b'//mydepot/test/COPYING-new ====\n'
                b'\n'
            ),
            caps={
                'scmtools': {
                    'perforce': {
                        'moved_files': True
                    }
                }
            })

    def test_diff_with_moved_files_cap_off(self):
        """Testing PerforceClient.diff with moved files and capability off"""
        self._test_diff_with_moved_files(expected_diff=(
            b'--- //mydepot/test/README\t//mydepot/test/README#2\n'
            b'+++ //mydepot/test/README\t2022-01-02 12:34:56\n'
            b'@@ -1 +0,0 @@\n'
            b'-This is a test.\n'
            b'--- //mydepot/test/README-new\t//mydepot/test/README-new#0\n'
            b'+++ //mydepot/test/README-new\t2022-01-02 12:34:56\n'
            b'@@ -0,0 +1 @@\n'
            b'+This is a mess.\n'
            b'--- //mydepot/test/COPYING\t//mydepot/test/COPYING#2\n'
            b'+++ //mydepot/test/COPYING\t2022-01-02 12:34:56\n'
            b'@@ -1 +0,0 @@\n'
            b'-Copyright 2013 Joe User.\n'
            b'--- //mydepot/test/COPYING-new\t//mydepot/test/COPYING-new#0\n'
            b'+++ //mydepot/test/COPYING-new\t2022-01-02 12:34:56\n'
            b'@@ -0,0 +1 @@\n'
            b'+Copyright 2013 Joe User.\n'
        ))

    def _test_diff_with_moved_files(self, expected_diff, caps={}):
        client = self.build_client()
        client.capabilities = Capabilities(caps)
        client.p4.repo_files = [
            {
                'depotFile': '//mydepot/test/README',
                'rev': '2',
                'action': 'move/delete',
                'change': '12345',
                'text': 'This is a test.\n',
            },
            {
                'depotFile': '//mydepot/test/README-new',
                'rev': '1',
                'action': 'move/add',
                'change': '12345',
                'text': 'This is a mess.\n',
            },
            {
                'depotFile': '//mydepot/test/COPYING',
                'rev': '2',
                'action': 'move/delete',
                'change': '12345',
                'text': 'Copyright 2013 Joe User.\n',
            },
            {
                'depotFile': '//mydepot/test/COPYING-new',
                'rev': '1',
                'action': 'move/add',
                'change': '12345',
                'text': 'Copyright 2013 Joe User.\n',
            },
        ]

        readme_file = make_tempfile()
        copying_file = make_tempfile()
        readme_file_new = make_tempfile()
        copying_file_new = make_tempfile()
        client.p4.print_file('//mydepot/test/README#2', readme_file)
        client.p4.print_file('//mydepot/test/COPYING#2', copying_file)
        client.p4.print_file('//mydepot/test/README-new#1', readme_file_new)
        client.p4.print_file('//mydepot/test/COPYING-new#1', copying_file_new)

        client.p4.where_files = {
            '//mydepot/test/README': readme_file,
            '//mydepot/test/COPYING': copying_file,
            '//mydepot/test/README-new': readme_file_new,
            '//mydepot/test/COPYING-new': copying_file_new,
        }

        client.p4.fstat_files = {
            '//mydepot/test/README': {
                'clientFile': readme_file,
                'movedFile': '//mydepot/test/README-new',
            },
            '//mydepot/test/README-new': {
                'clientFile': readme_file_new,
                'depotFile': '//mydepot/test/README-new',
            },
            '//mydepot/test/COPYING': {
                'clientFile': copying_file,
                'movedFile': '//mydepot/test/COPYING-new',
            },
            '//mydepot/test/COPYING-new': {
                'clientFile': copying_file_new,
                'depotFile': '//mydepot/test/COPYING-new',
            },
        }

        revisions = client.parse_revision_spec(['12345'])
        diff = client.diff(revisions)

        self.assertEqual(
            self._normalize_diff(client.diff(revisions)),
            {
                'changenum': '12345',
                'diff': expected_diff,
            })

    def test_parse_revision_spec_no_args(self):
        """Testing PerforceClient.parse_revision_spec with no specified
        revisions
        """
        client = self.build_client()

        self.assertEqual(
            client.parse_revision_spec(),
            {
                'base': PerforceClient.REVISION_CURRENT_SYNC,
                'tip': ('%sdefault'
                        % PerforceClient.REVISION_PENDING_CLN_PREFIX),
            })

    def test_parse_revision_spec_pending_cln(self):
        """Testing PerforceClient.parse_revision_spec with a pending
        changelist
        """
        class TestWrapper(P4Wrapper):
            def change(self, changelist):
                return [{
                    'Change': '12345',
                    'Date': '2013/12/19 11:32:45',
                    'User': 'example',
                    'Status': 'pending',
                    'Description': 'My change description\n',
                }]

        client = self.build_client(wrapper_cls=TestWrapper)

        self.assertEqual(
            client.parse_revision_spec(['12345']),
            {
                'base': PerforceClient.REVISION_CURRENT_SYNC,
                'tip': '%s12345' % PerforceClient.REVISION_PENDING_CLN_PREFIX,
            })

    def test_parse_revision_spec_submitted_cln(self):
        """Testing PerforceClient.parse_revision_spec with a submitted
        changelist
        """
        class TestWrapper(P4Wrapper):
            def change(self, changelist):
                return [{
                    'Change': '12345',
                    'Date': '2013/12/19 11:32:45',
                    'User': 'example',
                    'Status': 'submitted',
                    'Description': 'My change description\n',
                }]

        client = self.build_client(wrapper_cls=TestWrapper)

        self.assertEqual(
            client.parse_revision_spec(['12345']),
            {
                'base': '12344',
                'tip': '12345',
            })

    def test_parse_revision_spec_shelved_cln(self):
        """Testing PerforceClient.parse_revision_spec with a shelved
        changelist
        """
        class TestWrapper(P4Wrapper):
            def change(self, changelist):
                return [{
                    'Change': '12345',
                    'Date': '2013/12/19 11:32:45',
                    'User': 'example',
                    'Status': 'shelved',
                    'Description': 'My change description\n',
                }]

        client = self.build_client(wrapper_cls=TestWrapper)

        self.assertEqual(
            client.parse_revision_spec(['12345']),
            {
                'base': PerforceClient.REVISION_CURRENT_SYNC,
                'tip': '%s12345' % PerforceClient.REVISION_PENDING_CLN_PREFIX,
            })

    def test_parse_revision_spec_two_args(self):
        """Testing PerforceClient.parse_revision_spec with two changelists"""
        class TestWrapper(P4Wrapper):
            def change(self, changelist):
                change = {
                    'Change': str(changelist),
                    'Date': '2013/12/19 11:32:45',
                    'User': 'example',
                    'Description': 'My change description\n',
                }

                if changelist == '99' or changelist == '100':
                    change['Status'] = 'submitted'
                elif changelist == '101':
                    change['Status'] = 'pending'
                elif changelist == '102':
                    change['Status'] = 'shelved'
                else:
                    assert False

                return [change]

        client = self.build_client(wrapper_cls=TestWrapper)

        self.assertEqual(
            client.parse_revision_spec(['99', '100']),
            {
                'base': '99',
                'tip': '100',
            })

        with self.assertRaises(InvalidRevisionSpecError):
            client.parse_revision_spec(['99', '101'])

        with self.assertRaises(InvalidRevisionSpecError):
            client.parse_revision_spec(['99', '102'])

        with self.assertRaises(InvalidRevisionSpecError):
            client.parse_revision_spec(['101', '100'])

        with self.assertRaises(InvalidRevisionSpecError):
            client.parse_revision_spec(['102', '100'])

        with self.assertRaises(InvalidRevisionSpecError):
            client.parse_revision_spec(['102', '10284'])

    def test_parse_revision_spec_invalid_spec(self):
        """Testing PerforceClient.parse_revision_spec with invalid
        specifications
        """
        class TestWrapper(P4Wrapper):
            def change(self, changelist):
                return []

        client = self.build_client(wrapper_cls=TestWrapper)

        with self.assertRaises(InvalidRevisionSpecError):
            client.parse_revision_spec(['aoeu'])

        with self.assertRaises(TooManyRevisionsError):
            client.parse_revision_spec(['1', '2', '3'])

    def test_diff_exclude(self):
        """Testing PerforceClient.normalize_exclude_patterns"""
        repo_root = self.chdir_tmp()
        os.mkdir('subdir')
        cwd = os.getcwd()

        class ExcludeWrapper(P4Wrapper):
            def info(self):
                return {
                    'Client root': repo_root,
                }

        client = self.build_client(wrapper_cls=ExcludeWrapper)

        patterns = [
            '//depot/path',
            os.path.join(os.path.sep, 'foo'),
            'foo',
        ]

        normalized_patterns = [
            # Depot paths should remain unchanged.
            patterns[0],
            # "Absolute" paths (i.e., ones that begin with a path separator)
            # should be relative to the repository root.
            os.path.join(repo_root, patterns[1][1:]),
            # Relative paths should be relative to the current working
            # directory.
            os.path.join(cwd, patterns[2]),
        ]

        result = client.normalize_exclude_patterns(patterns)

        self.assertEqual(result, normalized_patterns)

    def _normalize_diff(self, diff_result):
        """Normalize a diff result for comparison.

        This will ensure that dates are all normalized to a fixed date
        string, making it possible to compare for equality.

        Version Added:
            4.0

        Args:
            diff_result (dict):
                The diff result.

        Returns:
            dict:
            The normalized diff result.
        """
        self.assertIsInstance(diff_result, dict)

        for key in ('diff', 'parent_diff'):
            if diff_result.get(key):
                diff_result[key] = re.sub(
                    br'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',
                    br'2022-01-02 12:34:56',
                    diff_result[key])

        return diff_result
