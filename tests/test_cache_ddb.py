from cache import ddb_backend
from cache.cache_ctrl import CacheController
from cache.sys_cache import ConvCache, SysCache
from cache.tau_cache import TAUCache


def test_ddb_backend_roundtrip(moto_cache_table):
    ddb_backend.set("ns", "key1", "value1", ttl=60)
    assert ddb_backend.get("ns", "key1") == "value1"


def test_ddb_backend_l1_hit_avoids_dynamodb(moto_cache_table):
    ddb_backend.set("ns", "key2", "value2", ttl=60)
    # Simulate DynamoDB becoming unreachable — L1 should still serve it.
    ddb_backend._table = False
    assert ddb_backend.get("ns", "key2") == "value2"


def test_ddb_backend_delete_removes_from_l1_and_table(moto_cache_table):
    ddb_backend.set("ns", "key3", "value3", ttl=60)
    ddb_backend.delete("ns", "key3")
    assert ddb_backend.get("ns", "key3") is None


def test_ddb_backend_miss_without_table_returns_none(monkeypatch):
    # Simulates DynamoDB being unreachable (no moto mock active) — the cache
    # must degrade to "always a miss", never raise into the request path.
    ddb_backend._l1.clear()
    monkeypatch.setattr(ddb_backend, "_get_table", lambda: None)
    assert ddb_backend.get("ns", "nope") is None


def test_sys_cache_write_read(moto_cache_table):
    cache = SysCache()
    cache.write("system_prompt", "hello", ttl=60)
    assert cache.read("system_prompt") == "hello"


def test_conv_cache_rolling_window(moto_cache_table):
    cache = ConvCache()
    for i in range(cache.LOOKBACK + 5):
        cache.append("session1", {"role": "user", "content": str(i)})
    window = cache.get_window("session1")
    assert len(window) == cache.LOOKBACK
    assert window[-1]["content"] == str(cache.LOOKBACK + 4)


def test_tau_cache_set_get_invalidate(moto_cache_table):
    cache = TAUCache()
    cache.set("session1", "context-blob")
    assert cache.get("session1") == "context-blob"
    cache.invalidate("session1")
    assert cache.get("session1") is None


def test_cache_controller_invalidate_clears_matching_break_vector(moto_cache_table):
    ctrl = CacheController()
    ctrl.write("prefixhash", "cached-response")
    assert ctrl.read("prefixhash") == "cached-response"

    ctrl.invalidate("model_switch")
    assert ctrl.check_break() is True
    assert ctrl.read("prefixhash") is None  # L1 cleared; DynamoDB item just ages out via TTL


def test_cache_controller_ignores_unknown_break_vector(moto_cache_table):
    ctrl = CacheController()
    ctrl.write("prefixhash", "cached-response")
    ctrl.invalidate("not_a_real_vector")
    assert ctrl.check_break() is False
    assert ctrl.read("prefixhash") == "cached-response"
