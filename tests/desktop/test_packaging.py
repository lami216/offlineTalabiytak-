import socket

from desktop_launcher import reserved_loopback_socket


def test_reserved_loopback_socket_binds_only_localhost():
    sock = reserved_loopback_socket()
    try:
        host, port = sock.getsockname()
        assert host == "127.0.0.1"
        assert port > 0
        with socket.socket() as other:
            try:
                other.bind(("127.0.0.1", port))
            except OSError:
                pass
            else:
                raise AssertionError("port was not reserved")
    finally:
        sock.close()
