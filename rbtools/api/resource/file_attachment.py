"""Resource definitions for file attachments.

Version Added:
    6.0:
    This was moved from :py:mod:`rbtools.api.resource`.
"""

from __future__ import annotations

from rbtools.api.resource.base import (
    ItemResource,
    ListResource,
    resource_mimetype,
)
from rbtools.api.resource.mixins import AttachmentUploadMixin


@resource_mimetype('application/vnd.reviewboard.org.file-attachment')
class FileAttachmentItemResource(ItemResource):
    """Item resource for file attachments.

    Version Added:
        6.0
    """


@resource_mimetype('application/vnd.reviewboard.org.file-attachments')
@resource_mimetype('application/vnd.reviewboard.org.user-file-attachments')
class FileAttachmentListResource(AttachmentUploadMixin,
                                 ListResource[FileAttachmentItemResource]):
    """List resource for file attachments."""
