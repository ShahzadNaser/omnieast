__version__ = "0.0.1"

try:
    from omnieast.overrides.trial_balance import apply as _apply_trial_balance_overrides

    _apply_trial_balance_overrides()

    from omnieast.overrides.accounting_period import apply as _apply_accounting_period_overrides
    _apply_accounting_period_overrides()
    
except ImportError:
    pass
