__version__ = "0.0.1"

try:
    from omnieast.overrides.trial_balance import apply as _apply_trial_balance_overrides

    _apply_trial_balance_overrides()
except ImportError:
    pass

try:
    from omnieast.overrides.report_script import apply as _apply_report_script_overrides

    _apply_report_script_overrides()
except ImportError:
    pass
