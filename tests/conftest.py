"""Conftest global de tests.

Provee un stub minimo del modulo `boto3.dynamodb.conditions` cuando
`boto3` no esta instalado en el entorno local. Los repositorios
DynamoDB importan `Attr` desde ese path para construir
`FilterExpression`; el stub permite que los tests unitarios con fakes
funcionen sin la dependencia real.

No reemplaza a `boto3` para llamadas reales a AWS.
"""

import sys
import types


def _ensure_boto3_conditions_stub() -> None:
    if "boto3.dynamodb.conditions" in sys.modules:
        return
    try:
        import boto3.dynamodb.conditions  # noqa: F401
        return
    except ImportError:
        pass

    boto3_mod = sys.modules.setdefault("boto3", types.ModuleType("boto3"))
    dynamodb_mod = sys.modules.setdefault(
        "boto3.dynamodb", types.ModuleType("boto3.dynamodb")
    )
    conditions_mod = types.ModuleType("boto3.dynamodb.conditions")

    class _Attr:
        def __init__(self, name: str) -> None:
            self.name = name

        def contains(self, value):
            return _Condition(self, "contains", value)

        def eq(self, value):
            return _Condition(self, "eq", value)

    class _Condition:
        def __init__(self, attr, op, value):
            self.attr = attr
            self.op = op
            self.value = value

        def __or__(self, other):
            return _OrCondition(self, other)

        def _evaluate(self, item: dict) -> bool:
            val = item.get(self.attr.name)
            if self.op == "eq":
                return val == self.value
            if self.op == "contains":
                if val is None:
                    return False
                try:
                    return self.value in val
                except TypeError:
                    return False
            return False

    class _OrCondition:
        def __init__(self, left, right):
            self.left = left
            self.right = right

        def _evaluate(self, item: dict) -> bool:
            return self.left._evaluate(item) or self.right._evaluate(item)

    conditions_mod.Attr = _Attr  # type: ignore[attr-defined]
    sys.modules["boto3.dynamodb.conditions"] = conditions_mod
    setattr(dynamodb_mod, "conditions", conditions_mod)
    setattr(boto3_mod, "dynamodb", dynamodb_mod)


_ensure_boto3_conditions_stub()
