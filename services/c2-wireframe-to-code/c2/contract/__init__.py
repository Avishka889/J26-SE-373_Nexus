"""The API contract: two arms, one shape, compared."""

from .rule_arm import generate_rule_contract
from .rules import ALL_RULES, RULE_IDS, ContractContext, validate_contract
from .vocab import canonical, slug

__all__ = [
    "ALL_RULES",
    "RULE_IDS",
    "ContractContext",
    "canonical",
    "generate_rule_contract",
    "slug",
    "validate_contract",
]
