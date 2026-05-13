from functools import lru_cache


@lru_cache
def get_dynamodb_resource():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for DynamoDB storage.") from exc

    return boto3.resource("dynamodb")


def get_table(table_name: str):
    return get_dynamodb_resource().Table(table_name)


def transact_put_items(puts: list[dict]):
    try:
        from boto3.dynamodb.types import TypeSerializer
    except ImportError as exc:
        raise RuntimeError("boto3 is required for DynamoDB storage.") from exc

    serializer = TypeSerializer()
    client = get_dynamodb_resource().meta.client
    transact_items = []
    for put in puts:
        item = {
            key: serializer.serialize(value)
            for key, value in put["item"].items()
            if value is not None
        }
        transact_items.append(
            {
                "Put": {
                    "TableName": put["table_name"],
                    "Item": item,
                    "ConditionExpression": put["condition_expression"],
                }
            }
        )

    return client.transact_write_items(TransactItems=transact_items)
