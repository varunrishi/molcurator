"""Optional automatic gallery export after PREDICT. Never changes tool results."""
import logging
import os
from pathlib import Path

from .viewer import export_prediction_gallery

log = logging.getLogger(__name__)


def publish_prediction_viewers(predictions, xyz_dir: Path):
    """Export ./viewers/index.json and up to N HTML previews.

    Set MOLCURATOR_VIEWERS=0 to disable, or MOLCURATOR_MAX_VIEWERS to
    limit HTML generation. The agent's Prediction models are untouched.
    """
    if os.getenv('MOLCURATOR_VIEWERS', '0').lower() in {'0','false','off','no'}:
        return None
    try:
        maximum = int(os.getenv('MOLCURATOR_MAX_VIEWERS', '30'))
        if maximum < 0:
            raise ValueError('MOLCURATOR_MAX_VIEWERS must be nonnegative')
        return export_prediction_gallery(predictions, Path(xyz_dir) / 'viewers', max_molecules=maximum)
    except Exception as exc:
        # Plotting must never break molecule prediction or alter statuses.
        log.warning('Optional molecule gallery failed: %s: %s', type(exc).__name__, exc)
        return None
