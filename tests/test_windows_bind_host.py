from windows.bind_host import is_local_only, resolve_bind_host


def test_default_is_this_pc_only():
    assert resolve_bind_host("") == "127.0.0.1"
    assert resolve_bind_host("   ") == "127.0.0.1"
    assert resolve_bind_host(None) == "127.0.0.1"


def test_explicit_choice_is_respected():
    assert resolve_bind_host(" 0.0.0.0 ") == "0.0.0.0"
    assert resolve_bind_host("192.168.1.20") == "192.168.1.20"


def test_is_local_only():
    assert is_local_only("127.0.0.1") and is_local_only("::1")
    assert not is_local_only("0.0.0.0") and not is_local_only("192.168.1.20")
