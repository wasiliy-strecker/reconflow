from decimal import Decimal
from unittest.mock import Mock

from reconflow.ai import cost_eur
from reconflow.config import Settings
from reconflow.db import Connection, bind_parameter


def test_data_api_binds_money_as_decimal_strings():
    assert bind_parameter("amount", Decimal("123.45")) == {
        "name": "amount",
        "value": {"stringValue": "123.45"},
        "typeHint": "DECIMAL",
    }
    assert bind_parameter("missing", None)["value"] == {"isNull": True}


def test_data_api_decodes_json_null_and_money_without_float():
    db = Connection(Settings(_env_file=None, db_driver="data_api"))
    db.client = Mock()
    db.transaction_id = "tx"
    db.client.execute_statement.return_value = {
        "columnMetadata": [
            {"name": "payload", "typeName": "jsonb"},
            {"name": "amount", "typeName": "numeric"},
            {"name": "optional", "typeName": "text"},
        ],
        "records": [
            [{"stringValue": '{"name":"A & B"}'}, {"stringValue": "1190.00"}, {"isNull": True}]
        ],
    }
    result = db.execute("SELECT payload,amount,optional FROM invoices WHERE id=:id", {"id": "x"})
    assert result == [{"payload": {"name": "A & B"}, "amount": "1190.00", "optional": None}]
    assert db.client.execute_statement.call_args.kwargs["parameters"] == [
        {"name": "id", "value": {"stringValue": "x"}}
    ]


def test_budget_prices_long_context_conservatively():
    c = Settings(_env_file=None)
    assert cost_eur(1000, 1000, c) == Decimal("0.00066000")
    assert cost_eur(1050000, 4000, c) == Decimal("0.23430000")
