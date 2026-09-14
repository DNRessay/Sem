import os

# Must be set before config.py (or anything importing it) is first imported,
# since pydantic-settings reads the environment at instantiation time.
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("GROQ_MODEL", "qwen/qwen3.8-27b")
os.environ.setdefault("NEON_DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("MODAL_EMBEDDINGS_URL", "")
os.environ.setdefault("MODAL_REPO_URL", "")
os.environ.setdefault("MODAL_REPO_SECRET", "")
os.environ.setdefault("CACHE_TABLE_NAME", "semblance-cache-test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest


@pytest.fixture
def moto_cache_table():
    """Spins up a mocked DynamoDB table matching template.yaml's CacheTable,
    and resets cache/ddb_backend's warm-start singletons around it so each
    test sees a clean table instead of a stale boto3 handle from a prior mock."""
    import boto3
    from moto import mock_aws

    from cache import ddb_backend

    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=os.environ["CACHE_TABLE_NAME"],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb_backend._table = None
        ddb_backend._l1.clear()
        yield
        ddb_backend._table = None
        ddb_backend._l1.clear()
