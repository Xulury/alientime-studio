"""Import every module that registers job handlers."""
from app.imaging import jobs as _imaging_jobs  # noqa: F401
from app.intel import jobs as _intel_jobs  # noqa: F401
from app.publish import jobs as _publish_jobs  # noqa: F401
