from django.utils.translation import gettext_lazy as _
"""Private PDF storage names and bounded document validation."""
import uuid

from django.core.exceptions import ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_CV_BYTES = 5 * 1024 * 1024


def cv_upload_path(instance, filename):
    # Never use applicant-supplied paths or names for storage.
    return f"cvs/{uuid.uuid4().hex}.pdf"


def validate_cv(upload):
    if upload.size > MAX_CV_BYTES:
        raise ValidationError(_("Your CV must be 5 MB or smaller."))
    if not upload.name.lower().endswith(".pdf"):
        raise ValidationError(_("Upload your CV as a PDF file."))
    try:
        upload.seek(0)
        if upload.read(5) != b"%PDF-":
            raise ValidationError(_("This file is not a valid PDF. Export your CV as a PDF and try again."))
        upload.seek(0)
        reader = PdfReader(upload, strict=True)
        if reader.is_encrypted:
            raise ValidationError(_("Upload a PDF without password protection."))
        if not reader.pages:
            raise ValidationError(_("Your PDF must contain at least one page."))
    except (PdfReadError, ValueError, KeyError, TypeError, RecursionError, OverflowError):
        raise ValidationError(_("We could not read this PDF. Export your CV as a new PDF and try again."))
    finally:
        upload.seek(0)
