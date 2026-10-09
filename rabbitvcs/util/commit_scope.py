"""Local repository identity checks for a single SVN commit."""

import os

import pysvn


class CommitScope:
    def __init__(self, client, target):
        self.client = client
        self.cache = {}
        self.target = self.repository(target, unversioned=True)

    def repository(self, path, unversioned=False):
        path = os.path.abspath(str(path))
        if path not in self.cache:
            try:
                info = self.client.info2(path, recurse=False)[0][1]
                identity = (info.get('repos_UUID'), info.get('repos_root_URL'))
                self.cache[path] = identity if all(identity) else None
            except (pysvn.ClientError, IndexError):
                self.cache[path] = None
        identity = self.cache[path]
        # New files inherit the repository of their nearest versioned parent.
        # Do not do this for versioned files: an info failure must fail closed.
        if identity is None and unversioned:
            parent = os.path.dirname(path)
            if parent != path:
                return self.repository(parent, unversioned=True)
        return identity

    def permits(self, path, unversioned=False):
        return self.target is not None and self.repository(path, unversioned) == self.target
