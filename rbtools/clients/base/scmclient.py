"""Base class for interfacing with source code management tools.

Version Added:
    4.0
"""

from __future__ import unicode_literals

import logging
import re
from typing import Optional, cast

from typing_extensions import final

import six

from rbtools.clients.base.patch import PatchResult
from rbtools.clients.errors import SCMClientDependencyError, SCMError
from rbtools.deprecation import RemovedInRBTools50Warning
from rbtools.utils.process import execute


class BaseSCMClient(object):
    """A base class for interfacing with a source code management tool.

    These are used for fetching repository information and generating diffs.

    Callers must run :py:meth:`setup` or :py:meth:`has_dependencies` before
    calling methods on this tool.

    Version Changed:
        4.0:
        * Moved from :py:mod:`rbtools.clients` into
          :py:mod:`rbtools.clients.base.scmclient` and renamed from
          ``SCMClient`` to ``BaseSCMClient``.

        * A call to :py:meth:`setup` or :py:meth:`has_dependencies` will be
          required starting in RBTools 5.0.

    Attributes:
        config (dict):
            Any user configuration loaded via :file:`.reviewboardrc` files.
            This may be empty.

        is_setup (bool):
            Whether the client is set up and ready for operations. Operations
            may fail if this is ``False``.

            Callers must call :py:meth:`setup` or :py:meth:`has_dependencies`
            before performing operations using this client.

            Version Added:
                4.0

        options (argparse.Namespace):
            Any command line arguments passed to a tool running this client.
            This may be empty, and makes assumptions about which command line
            arguments are registered with a command. It's intended for use
            within RBTools.
    """

    #: The unique ID of the client.
    #:
    #: Version Added:
    #:     4.0:
    #:     This will be required in RBTools 5.0.
    #:
    #: Type:
    #:     str
    scmclient_id: str = ''

    #: The name of the client.
    #:
    #: Type:
    #:     unicode
    name = None

    #: A comma-separated list of SCMClient names on the server
    #:
    #: Version Added:
    #:    3.0
    #:
    #: Type:
    #:     unicode
    server_tool_names = None

    #: Whether the SCM uses server-side changesets
    #:
    #: Version Added:
    #:     3.0
    #:
    #: Type:
    #:     bool
    supports_changesets = False

    #: Whether the SCM client can generate a commit history.
    #:
    #: Type:
    #:     bool
    supports_commit_history = False

    #: Whether the SCM client's diff method takes the ``extra_args`` parameter.
    #:
    #: Type:
    #:     bool
    supports_diff_extra_args = False

    #: Whether the SCM client supports excluding files from the diff.
    #:
    #: Type:
    #:     bool
    supports_diff_exclude_patterns = False

    #: Whether the SCM client can generate diffs without renamed files.
    #:
    #: Type:
    #:     bool
    supports_no_renames = False

    #: Whether the SCM client supports generating parent diffs.
    #:
    #: Version Added:
    #:     3.0
    #:
    #: Type:
    #:     bool
    supports_parent_diffs = False

    #: Whether the SCM client supports reverting patches.
    #:
    #: Type:
    #:     bool
    supports_patch_revert = False

    #: Whether commits can be amended.
    #:
    #: Type:
    #:     bool
    can_amend_commit = False

    #: Whether the SCM can create merges.
    #:
    #: Type:
    #:     bool
    can_merge = False

    #: Whether commits can be pushed upstream.
    #:
    #: Type:
    #:     bool
    can_push_upstream = False

    #: Whether branch names can be deleted.
    #:
    #: Type:
    #:     bool
    can_delete_branch = False

    #: Whether new branches can be created.
    #:
    #: Type:
    #:     bool
    can_branch = False

    #: Whether new bookmarks can be created.
    #:
    #: Type:
    #:     bool
    can_bookmark = False

    #: Whether commits can be squashed during merge.
    #:
    #: Type:
    #:     bool
    can_squash_merges = False

    def __init__(self, config=None, options=None):
        """Initialize the client.

        Args:
            config (dict, optional):
                The loaded user config.

            options (argparse.Namespace, optional):
                The parsed command line arguments.
        """
        self.config = config or {}
        self.options = options
        self.capabilities = None
        self.is_setup: bool = False

        self._has_deps: Optional[bool] = None

    @property
    def entrypoint_name(self) -> str:
        """An alias for the SCMClient ID.

        This is here for backwards-compatibility purposes.

        Deprecated:
            4.0:
            Callers should use :py:attr:`scmclient_id`. This attribute will
            be removed in RBTools 5.0.
        """
        cls_name = type(self).__name__

        RemovedInRBTools50Warning.warn(
            '%s.entrypoint_name is deprecated. Please use %s.scmclient_id '
            'instead. This will be removed in RBTools 5.0.'
            % (cls_name, cls_name))

        return self.scmclient_id

    @final
    def setup(self) -> None:
        """Set up the client.

        This will perform checks to ensure the client can be used. Callers
        should make sure to either call this method or
        :py:meth:`has_dependencies` before performing any other operations
        on this client.

        If checks succeed, :py:attr:`is_setup` will be ``True``, and operations
        using this client can be performed.

        If checks fail, an exception may be raised, and :py:attr:`is_setup`
        will be ``False``.

        Version Added:
            4.0

        Raises:
            rbtools.clients.errors.SCMClientDependencyError:
                One or more required dependencies are missing.
        """
        if self.is_setup:
            # Silently return. We may want to make this a warning in a future
            # version, or enforce call order, but it's currently harmless to
            # allow multiple calls.
            return

        try:
            self.check_dependencies()
            self._has_deps = True
        except SCMClientDependencyError:
            self._has_deps = False
            raise

        self.is_setup = True

    def has_dependencies(
        self,
        expect_checked: bool = False,
    ) -> bool:
        """Return whether all dependencies for the client are available.

        Either this or :py:meth:`setup` must be called before any operations
        are performed with this client.

        Version Added:
            4.0

        Args:
            expect_checked (bool, optional):
                Whether the caller expects that dependency checking has
                already been done.

                If ``True``, and dependencies have not yet been checked via
                :py:meth:`check_dependencies`, this will raise a deprecation
                warning.

                Starting in RBTools 4.0, this will raise an exception if
                :py:meth:`check_dependencies` hasn't yet been called.

        Returns:
            bool:
            ``True`` if dependencies are all available. ``False`` if one or
            more are not.
        """
        if self._has_deps is None:
            if expect_checked:
                RemovedInRBTools50Warning.warn(
                    'Either %(cls_name)s.setup() or '
                    '%(cls_name)s.has_dependencies() must be called before '
                    'other functions are used. This will be required '
                    'starting in RBTools 5.0.'
                    % {
                        'cls_name': type(self).__name__,
                    })

            try:
                self.setup()
            except SCMClientDependencyError:
                pass

        return cast(bool, self._has_deps)

    def check_dependencies(self) -> None:
        """Check whether the base dependencies needed are available.

        This is responsible for checking for any command line tools or Python
        modules required to consider this client as an option when scanning
        repositories or selecting a specific client.

        This should not check for diff implementations or anything specific
        about a local filesystem. It's merely a first-pass dependency check.

        This function is normally called via :py:meth:`setup` (which will
        re-raise any exceptions here) or :py:meth:`has_dependencies`. It
        doesn't need to be called manually unless attempting to re-generate
        the exception.

        Subclasses can log any failed checks in the debug log, to help with
        debugging missing tools. If checking against multiple possible names,
        they may also record information needed to locate the matching
        executable for future operations.

        It's recommended to use :py:meth:`rbtools.utils.checks.check_install`
        to help with executable dependency checks.

        Version Added:
            4.0

        Raises:
            rbtools.clients.errors.SCMClientDependencyError:
                One or more required dependencies are missing.
        """
        pass

    def is_remote_only(self):
        """Return whether this repository is operating in remote-only mode.

        For some SCMs and some operations, it may be possible to operate
        exclusively with a remote server and have no working directory.

        Version Added:
            3.0

        Returns:
            bool:
            Whether this repository is operating in remote-only mode.
        """
        return False

    def get_local_path(self) -> Optional[str]:
        """Return the local path to the working tree.

        This is expected to be overridden by subclasses.

        Version Added:
            3.0

        Returns:
            str:
            The filesystem path of the repository on the client system.
        """
        logging.warning('%s should implement a get_local_path method',
                        self.__class__)
        info = self.get_repository_info()
        return info and info.local_path

    def get_repository_info(self):
        """Return repository information for the current working tree.

        This is expected to be overridden by subclasses.

        Version Added:
            3.0

        Returns:
            rbtools.clients.base.repository.RepositoryInfo:
            The repository info structure.
        """
        return None

    def find_matching_server_repository(self, repositories):
        """Find a match for the repository on the server.

        Version Added:
            3.0

        Args:
            repositories (rbtools.api.resource.ListResource):
                The fetched repositories.

        Returns:
            tuple:
            A 2-tuple of :py:class:`~rbtools.api.resource.ItemResource`. The
            first item is the matching repository, and the second is the
            repository info resource.
        """
        return None, None

    def get_repository_name(self):
        """Return any repository name configured in the repository.

        This is used as a fallback from the standard config options, for
        repository types that support configuring the name in repository
        metadata.

        Version Added:
            3.0

        Returns:
            unicode:
            The configured repository name, or None.
        """
        return None

    def check_options(self):
        """Verify the command line options.

        This is expected to be overridden by subclasses, if they need to do
        specific validation of the command line.

        Raises:
            rbtools.clients.errors.OptionsCheckError:
                The supplied command line options were incorrect. In
                particular, if a file has history scheduled with the commit,
                the user needs to explicitly choose what behavior they want.
        """
        pass

    def get_changenum(self, revisions):
        """Return the change number for the given revisions.

        This is only used when the client is supposed to send a change number
        to the server (such as with Perforce).

        Args:
            revisions (dict):
                A revisions dictionary as returned by ``parse_revision_spec``.

        Returns:
            unicode:
            The change number to send to the Review Board server.
        """
        return None

    def scan_for_server(self, repository_info):
        """Find the server path.

        This will search for the server name in the .reviewboardrc config
        files. These are loaded with the current directory first, and searching
        through each parent directory, and finally $HOME/.reviewboardrc last.

        Args:
            repository_info (rbtools.clients.base.repository.RepositoryInfo):
                The repository information structure.

        Returns:
            unicode:
            The Review Board server URL, if available.
        """
        return None

    def parse_revision_spec(self, revisions=[]):
        """Parse the given revision spec.

        The 'revisions' argument is a list of revisions as specified by the
        user. Items in the list do not necessarily represent a single revision,
        since the user can use SCM-native syntaxes such as "r1..r2" or "r1:r2".
        SCMTool-specific overrides of this method are expected to deal with
        such syntaxes.

        Args:
            revisions (list of unicode, optional):
                A list of revisions as specified by the user. Items in the list
                do not necessarily represent a single revision, since the user
                can use SCM-native syntaxes such as ``r1..r2`` or ``r1:r2``.
                SCMTool-specific overrides of this method are expected to deal
                with such syntaxes.

        Raises:
            rbtools.clients.errors.InvalidRevisionSpecError:
                The given revisions could not be parsed.

            rbtools.clients.errors.TooManyRevisionsError:
                The specified revisions list contained too many revisions.

        Returns:
            dict:
            A dictionary with the following keys:

            ``base`` (:py:class:`unicode`):
                A revision to use as the base of the resulting diff.

            ``tip`` (:py:class:`unicode`):
                A revision to use as the tip of the resulting diff.

            ``parent_base`` (:py:class:`unicode`, optional):
                The revision to use as the base of a parent diff.

            ``commit_id`` (:py:class:`unicode`, optional):
                The ID of the single commit being posted, if not using a
                range.

            Additional keys may be included by subclasses for their own
            internal use.

            These will be used to generate the diffs to upload to Review Board
            (or print). The diff for review will include the changes in (base,
            tip], and the parent diff (if necessary) will include (parent,
            base].

            If a single revision is passed in, this will return the parent of
            that revision for "base" and the passed-in revision for "tip".

            If zero revisions are passed in, this will return revisions
            relevant for the "current change". The exact definition of what
            "current" means is specific to each SCMTool backend, and documented
            in the implementation classes.
        """
        return {
            'base': None,
            'tip': None,
        }

    def get_tree_matches_review_request(self, review_request, revisions,
                                        **kwargs):
        """Return whether a review request matches revisions or tree state.

        This works along with review request matching in tools like
        :command:`rbt post` to match state in a review request (such as in
        ``extra_data``) with the state in the local tree (such as the local
        branch or SCM-specific identifiers other than a commit ID).

        Subclasses can override this to implement their own matching logic.
        By default, no additional logic is implemented.

        Version Added:
            3.1

        Args:
            review_request (rbtools.api.resource.ReviewRequestResource):
                The review request being matched.

            revisions (dict):
                A dictionary of revisions, as returned by
                :py:meth:`parse_revision_spec`.

            **kwargs (dict, unused):
                Additional keyword arguments, for future expansion.

        Returns:
            bool:
            ``True`` if the review request is considered an exact match.

            ``False`` if the review request should be explicitly discarded
            as a possible match.

            ``None`` if a match could not be determined based on available
            information.
        """
        return None

    def diff(self, revisions, include_files=[], exclude_patterns=[],
             no_renames=False, repository_info=None, extra_args=[]):
        """Perform a diff using the given revisions.

        This is expected to be overridden by subclasses.

        Args:
            revisions (dict):
                A dictionary of revisions, as returned by
                :py:meth:`parse_revision_spec`.

            include_files (list of unicode, optional):
                A list of files to whitelist during the diff generation.

            exclude_patterns (list of unicode, optional):
                A list of shell-style glob patterns to blacklist during diff
                generation.

            repository_info (rbtools.clients.base.repository.RepositoryInfo,
                             optional):
                The repository info structure.

            extra_args (list, unused):
                Additional arguments to be passed to the diff generation.

            **kwargs (dict, unused):
                Unused keyword arguments.

        Returns:
            dict:
            A dictionary containing:

            Keys:
                diff (bytes):
                    The contents of the diff to upload.

                parent_diff (bytes, optional):
                    The contents of the parent diff, if available.

                commit_id (unicode, optional):
                    The commit ID to include when posting, if available.

                base_commit_id (unicode, optional):
                    The ID of the commit that the change is based on, if
                    available.  This is necessary for some hosting services
                    that don't provide individual file access.

                review_request_extra_data (dict, optional):
                    A dictionary of ``extra_data`` keys to set on the review
                    request (when posting to Review Board 3.0 or higher).

                    If posting a brand-new review request, this will set the
                    fields on the review request itself.

                    If updating a review request, this will set them on the
                    draft.

                    This may contain structured data. It will be sent to the
                    server as part of a JSON Merge Patch.

                    Version Added:
                        3.1
        """
        return {
            'diff': None,
            'parent_diff': None,
            'commit_id': None,
            'base_commit_id': None,
            'review_request_extra_data': None,
        }

    def get_commit_history(self, revisions):
        """Return the commit history between the given revisions.

        Derived classes must override this method if they support posting with
        history.

        Args:
            revisions (dict):
                The parsed revision spec to use to generate the history.

        Returns:
            list of dict:
            The history entries.
        """
        raise NotImplementedError

    def _get_p_number(self, base_path, base_dir):
        """Return the appropriate value for the -p argument to patch.

        This function returns an integer. If the integer is -1, then the -p
        option should not be provided to patch. Otherwise, the return value is
        the argument to :command:`patch -p`.

        Args:
            base_path (unicode):
                The relative path beetween the repository root and the
                directory that the diff file was generated in.

            base_dir (unicode):
                The current relative path between the repository root and the
                user's working directory.

        Returns:
            int:
            The prefix number to pass into the :command:`patch` command.
        """
        if base_path and base_dir.startswith(base_path):
            return base_path.count('/') + 1
        else:
            return -1

    def _strip_p_num_slashes(self, files, p_num):
        """Strip the smallest prefix containing p_num slashes from filenames.

        To match the behavior of the :command:`patch -pX` option, adjacent
        slashes are counted as a single slash.

        Args:
            files (list of unicode):
                The filenames to process.

            p_num (int):
                The number of prefixes to strip.

        Returns:
            list of unicode:
            The processed list of filenames.
        """
        if p_num > 0:
            regex = re.compile(r'[^/]*/+')
            return [regex.sub('', f, p_num) for f in files]
        else:
            return files

    def has_pending_changes(self):
        """Return whether there are changes waiting to be committed.

        Derived classes should override this method if they wish to support
        checking for pending changes.

        Returns:
            bool:
            ``True`` if the working directory has been modified or if changes
            have been staged in the index.
        """
        raise NotImplementedError

    def apply_patch(self, patch_file, base_path, base_dir, p=None,
                    revert=False):
        """Apply the patch and return a PatchResult indicating its success.

        Args:
            patch_file (unicode):
                The name of the patch file to apply.

            base_path (unicode):
                The base path that the diff was generated in.

            base_dir (unicode):
                The path of the current working directory relative to the root
                of the repository.

            p (unicode, optional):
                The prefix level of the diff.

            revert (bool, optional):
                Whether the patch should be reverted rather than applied.

        Returns:
            rbtools.clients.base.patch.PatchResult:
            The result of the patch operation.
        """
        # Figure out the -p argument for patch. We override the calculated
        # value if it is supplied via a commandline option.
        p_num = p or self._get_p_number(base_path, base_dir)

        cmd = ['patch']

        if revert:
            cmd.append('-R')

        try:
            p_num = int(p_num)
        except ValueError:
            p_num = 0
            logging.warning('Invalid -p value: %s; assuming zero.', p_num)

        if p_num is not None:
            if p_num >= 0:
                cmd.append('-p%d' % p_num)
            else:
                logging.warning('Unsupported -p value: %d; assuming zero.',
                                p_num)

        cmd.extend(['-i', six.text_type(patch_file)])

        # Ignore return code 2 in case the patch file consists of only empty
        # files, which 'patch' can't handle. Other 'patch' errors also give
        # return code 2, so we must check the command output.
        rc, patch_output = execute(cmd, extra_ignore_errors=(2,),
                                   return_error_code=True)
        only_garbage_in_patch = ('patch: **** Only garbage was found in the '
                                 'patch input.\n')

        if (patch_output and patch_output.startswith('patch: **** ') and
            patch_output != only_garbage_in_patch):
            raise SCMError('Failed to execute command: %s\n%s'
                           % (cmd, patch_output))

        # Check the patch for any added/deleted empty files to handle.
        if self.supports_empty_files():
            try:
                with open(patch_file, 'rb') as f:
                    patch = f.read()
            except IOError as e:
                logging.error('Unable to read file %s: %s', patch_file, e)
                return

            patched_empty_files = self.apply_patch_for_empty_files(
                patch, p_num, revert=revert)

            # If there are no empty files in a "garbage-only" patch, the patch
            # is probably malformed.
            if (patch_output == only_garbage_in_patch and
                not patched_empty_files):
                raise SCMError('Failed to execute command: %s\n%s'
                               % (cmd, patch_output))

        # TODO: Should this take into account apply_patch_for_empty_files ?
        #       The return value of that function is False both when it fails
        #       and when there are no empty files.
        return PatchResult(applied=(rc == 0), patch_output=patch_output)

    def create_commit(self, message, author, run_editor,
                      files=[], all_files=False):
        """Create a commit based on the provided message and author.

        Derived classes should override this method if they wish to support
        committing changes to their repositories.

        Args:
            message (unicode):
                The commit message to use.

            author (object):
                The author of the commit. This is expected to have ``fullname``
                and ``email`` attributes.

            run_editor (bool):
                Whether to run the user's editor on the commmit message before
                committing.

            files (list of unicode, optional):
                The list of filenames to commit.

            all_files (bool, optional):
                Whether to commit all changed files, ignoring the ``files``
                argument.

        Raises:
            NotImplementedError:
                The client does not support creating commits.

            rbtools.clients.errors.CreateCommitError:
                The commit message could not be created. It may have been
                aborted by the user.
        """
        raise NotImplementedError

    def get_commit_message(self, revisions):
        """Return the commit message from the commits in the given revisions.

        This pulls out the first line from the commit messages of the given
        revisions. That is then used as the summary.

        Args:
            revisions (dict):
                A dictionary as returned by :py:meth:`parse_revision_spec`.

        Returns:
            dict:
            A dictionary containing ``summary`` and ``description`` keys,
            matching the first line of the commit message and the remainder,
            respectively.
        """
        commit_message = self.get_raw_commit_message(revisions)
        lines = commit_message.splitlines()

        if not lines:
            return None

        result = {
            'summary': lines[0],
        }

        # Try to pull the body of the commit out of the full commit
        # description, so that we can skip the summary.
        if len(lines) >= 3 and lines[0] and not lines[1]:
            result['description'] = '\n'.join(lines[2:]).strip()
        else:
            result['description'] = commit_message

        return result

    def delete_branch(self, branch_name, merged_only=True):
        """Delete the specified branch.

        Args:
            branch_name (unicode):
                The name of the branch to delete.

            merged_only (bool, optional):
                Whether to limit branch deletion to only those branches which
                have been merged into the current HEAD.
        """
        raise NotImplementedError

    def merge(self, target, destination, message, author, squash=False,
              run_editor=False, close_branch=True):
        """Merge the target branch with destination branch.

        Args:
            target (unicode):
                The name of the branch to merge.

            destination (unicode):
                The name of the branch to merge into.

            message (unicode):
                The commit message to use.

            author (object):
                The author of the commit. This is expected to have ``fullname``
                and ``email`` attributes.

            squash (bool, optional):
                Whether to squash the commits or do a plain merge.

            run_editor (bool, optional):
                Whether to run the user's editor on the commmit message before
                committing.

            close_branch (bool, optional):
                Whether to close/delete the merged branch.

        Raises:
            rbtools.clients.errors.MergeError:
                An error occurred while merging the branch.
        """
        raise NotImplementedError

    def push_upstream(self, remote_branch):
        """Push the current branch to upstream.

        Args:
            remote_branch (unicode):
                The name of the branch to push to.

        Raises:
            rbtools.client.errors.PushError:
                The branch was unable to be pushed.
        """
        raise NotImplementedError

    def get_raw_commit_message(self, revisions):
        """Extract the commit messages on the commits in the given revisions.

        Derived classes should override this method in order to allow callers
        to fetch commit messages. This is needed for description guessing.

        If a derived class is unable to fetch the description, ``None`` should
        be returned.

        Callers that need to differentiate the summary from the description
        should instead use get_commit_message().

        Args:
            revisions (dict):
                A dictionary containing ``base`` and ``tip`` keys.

        Returns:
            unicode:
            The commit messages of all commits between (base, tip].
        """
        raise NotImplementedError

    def get_current_branch(self):
        """Return the repository branch name of the current directory.

        Derived classes should override this method if they are able to
        determine the current branch of the working directory.

        Returns:
            unicode:
            A string with the name of the current branch. If the branch is
            unable to be determined, returns ``None``.
        """
        raise NotImplementedError

    def supports_empty_files(self):
        """Return whether the server supports added/deleted empty files.

        Returns:
            bool:
            ``True`` if the Review Board server supports added or deleted empty
            files.
        """
        return False

    def apply_patch_for_empty_files(self, patch, p_num, revert=False):
        """Return whether any empty files in the patch are applied.

        Args:
            patch (bytes):
                The contents of the patch.

            p_num (unicode):
                The prefix level of the diff.

            revert (bool, optional):
                Whether the patch should be reverted rather than applied.

        Returns:
            ``True`` if there are empty files in the patch. ``False`` if there
            were no empty files, or if an error occurred while applying the
            patch.
        """
        raise NotImplementedError

    def amend_commit_description(self, message, revisions=None):
        """Update a commit message to the given string.

        Args:
            message (unicode):
                The commit message to use when amending the commit.

            revisions (dict, optional):
                A dictionary of revisions, as returned by
                :py:meth:`parse_revision_spec`. This provides compatibility
                with SCMs that allow modifications of multiple changesets at
                any given time, and will amend the change referenced by the
                ``tip`` key.

        Raises:
            rbtools.clients.errors.AmendError:
                The amend operation failed.
        """
        raise NotImplementedError
