#!/usr/bin/env python3
"""Tests de la couche d'envoi (`sender.py`).

Couvre la résolution de la famille de socket (`AF_INET` vs `AF_INET6`) pour
`--hep-host`, jusqu'ici toujours forcée à `AF_INET` ce qui faisait
silencieusement échouer tout envoi vers un collecteur HOMER en IPv6, ainsi
que le transport TCP/TLS (`TCPSender`) : réutilisation de connexion,
construction du contexte TLS (`tls_verify`, `tls_ca_file`) et gestion des
échecs de connexion/poignée de main, ainsi que le retry/backoff exponentiel
sur échec d'envoi (`--hep-retries`/`--hep-retry-backoff`).
"""

from __future__ import annotations

import gzip
import socket
import ssl
import time

import pytest

from oxo_hep_bridge.hep import ChunkType, HepPacket, decode
from oxo_hep_bridge.sender import NullSender, Sender, TCPSender, UDPSender, make_sender


def _packet() -> HepPacket:
    return HepPacket(src_ip="127.0.0.1", dst_ip="127.0.0.1", payload=b'{"x":1}')


def _ipv6_runtime_available() -> bool:
    """Détecte l'IPv6 disponible à l'exécution (pas seulement compilé) : `socket.has_ipv6`
    est vrai dès que Python est compilé avec le support IPv6, même si le noyau/hôte
    l'a désactivé (cas de ce bac à sable, sans `/proc/net/if_inet6`) — d'où la
    tentative réelle d'ouverture d'une socket `AF_INET6`."""
    if not socket.has_ipv6:
        return False
    try:
        probe = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    except OSError:
        return False
    probe.close()
    return True


requires_ipv6 = pytest.mark.skipif(
    not _ipv6_runtime_available(),
    reason="IPv6 non disponible dans cet environnement d'exécution",
)


class _FakeStreamSocket:
    """Socket TCP factice : connect()/sendall()/close() sans I/O réseau réelle.

    Réutilisée par tous les tests `TCPSender` ci-dessous (clair et TLS), avec
    sous-classement ponctuel quand un test a besoin de faire échouer
    connect()/sendall() spécifiquement.
    """

    def __init__(self, family=socket.AF_INET, socktype=socket.SOCK_STREAM):
        self.family = family
        self.socktype = socktype
        self.connected_to: tuple | None = None
        self.sent: list[bytes] = []
        self.sockopts: list[tuple] = []
        self.closed = False

    def connect(self, addr):
        self.connected_to = addr

    def setsockopt(self, level, optname, value):
        self.sockopts.append((level, optname, value))

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True


def test_udp_sender_uses_af_inet_for_ipv4_literal():
    sender = UDPSender(host="192.0.2.10", port=9060)
    try:
        assert sender.send(_packet()) is True
        assert sender._sock is not None
        assert sender._sock.family == socket.AF_INET
        assert sender._sockaddr == ("192.0.2.10", 9060)
    finally:
        sender.close()


@requires_ipv6
def test_udp_sender_uses_af_inet6_for_ipv6_literal():
    sender = UDPSender(host="::1", port=9060)
    try:
        assert sender.send(_packet()) is True
        assert sender._sock is not None
        assert sender._sock.family == socket.AF_INET6
        # sockaddr IPv6 = (host, port, flowinfo, scope_id)
        assert sender._sockaddr[0] == "::1"
        assert sender._sockaddr[1] == 9060
    finally:
        sender.close()


def test_udp_sender_resolves_hostname_via_getaddrinfo(monkeypatch):
    """Un nom d'hôte (pas seulement un littéral IP) doit être résolu, et la
    socket créée avec la famille renvoyée par la résolution — indépendamment
    du support IPv6 réel de la machine de test, la création de socket est
    donc mockée elle aussi (seul le routage `getaddrinfo -> socket()` est
    sous test ici, pas la pile réseau)."""
    calls = []
    created_families = []

    def fake_getaddrinfo(host, port, *args, **kwargs):
        calls.append(host)
        return [(socket.AF_INET6, socket.SOCK_DGRAM, 0, "", ("2001:db8::1", port, 0, 0))]

    class FakeSocket:
        def __init__(self, family, socktype):
            created_families.append(family)
            self.family = family

        def connect(self, addr):
            pass

        def sendto(self, *args, **kwargs):
            return len(args[0]) if args else 0

        def close(self):
            pass

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "socket", FakeSocket)

    sender = UDPSender(host="homer.example.invalid", port=9060)
    try:
        assert sender.send(_packet()) is True
        assert "homer.example.invalid" in calls
        assert created_families == [socket.AF_INET6]
        assert sender._sockaddr[0] == "2001:db8::1"
    finally:
        sender.close()


def test_udp_sender_resolution_failure_returns_false_and_logs(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        raise socket.gaierror("nom introuvable")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    sender = UDPSender(host="ne-resout-pas.invalid", port=9060)
    assert sender.send(_packet()) is False
    # aucune socket ne doit rester ouverte après un échec
    assert sender._sock is None


def test_udp_sender_send_failure_resets_socket_for_retry(monkeypatch):
    sender = UDPSender(host="192.0.2.10", port=9060)

    class BoomSocket:
        family = socket.AF_INET

        def sendto(self, *args, **kwargs):
            raise OSError("réseau injoignable")

        def close(self):
            pass

    def _fake_connect():
        return BoomSocket()

    monkeypatch.setattr(sender, "_connect", _fake_connect)
    sender._sock = BoomSocket()  # simule une socket déjà ouverte

    assert sender.send(_packet()) is False
    assert sender._sock is None
    assert sender._sockaddr == ()


def test_null_sender_send_encodes_and_logs():
    """NullSender (dry-run) doit encoder réellement le paquet — pour valider
    l'encodeur sans réseau — et retourner True sans jamais ouvrir de socket."""
    sender = NullSender()
    assert sender.send(_packet()) is True


# --- Classe de base Sender : défauts hérités par NullSender et tout sender
# factice de test qui ne les redéfinit pas (Bridge.run() s'appuie dessus
# sans hasattr()/getattr() — voir bridge.py et pyproject.toml [tool.mypy]) ---


def test_sender_base_class_retry_count_defaults_to_zero():
    """`Sender.retry_count` vaut 0 par défaut, hérité tel quel par tout
    sender qui ne le redéfinit pas (NullSender, senders factices de test)."""
    assert Sender().retry_count == 0


def test_sender_base_class_close_is_a_noop():
    """`Sender.close()` ne fait rien par défaut (pas de ressource réseau à
    libérer) et ne doit jamais lever — NullSender en hérite tel quel."""
    Sender().close()  # ne doit pas lever
    NullSender().close()  # idem, NullSender ne surcharge pas close()


def test_sender_base_class_send_raises_not_implemented():
    """`Sender` est une interface : send() n'est utilisable que sur une
    sous-classe qui la surcharge (UDPSender, TCPSender, NullSender...)."""
    with pytest.raises(NotImplementedError):
        Sender().send(_packet())


def test_udp_sender_reuses_socket_across_sends(monkeypatch):
    """Comme TCPSender, UDPSender doit réutiliser sa socket d'un envoi à
    l'autre plutôt que d'en recréer une à chaque paquet."""
    created = []

    class FakeDgramSocket:
        def __init__(self, family, socktype):
            created.append(self)
            self.sent: list[bytes] = []

        def connect(self, addr):
            pass

        def sendto(self, data, addr):
            self.sent.append(data)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", FakeDgramSocket)

    sender = UDPSender(host="192.0.2.10", port=9060)
    try:
        assert sender.send(_packet()) is True
        assert sender.send(_packet()) is True
        assert len(created) == 1
        assert len(created[0].sent) == 2
    finally:
        sender.close()


def test_udp_sender_close_is_idempotent():
    sender = UDPSender(host="127.0.0.1", port=9060)
    sender.send(_packet())
    sender.close()
    assert sender._sock is None
    sender.close()  # ne doit pas lever
    assert sender._sock is None


# --- TCPSender : transport en clair -----------------------------------------


def test_tcp_sender_resolves_ipv4_literal_to_af_inet(monkeypatch):
    created: list[_FakeStreamSocket] = []
    monkeypatch.setattr(
        socket,
        "socket",
        lambda family, socktype: created.append(_FakeStreamSocket(family, socktype)) or created[-1],
    )

    sender = TCPSender(host="192.0.2.10", port=9060)
    try:
        assert sender.send(_packet()) is True
        assert created[0].family == socket.AF_INET
        assert created[0].socktype == socket.SOCK_STREAM
        assert created[0].connected_to == ("192.0.2.10", 9060)
    finally:
        sender.close()


def test_tcp_sender_resolves_ipv6_literal_to_af_inet6(monkeypatch):
    """`getaddrinfo()` résout un littéral IPv6 par simple analyse de la
    chaîne, sans nécessiter de support IPv6 noyau (vérifié séparément dans ce
    bac à sable) — seule l'ouverture d'une socket AF_INET6 réelle
    l'exigerait, d'où le mock de `socket.socket` plutôt qu'un `@requires_ipv6`."""
    created: list[_FakeStreamSocket] = []
    monkeypatch.setattr(
        socket,
        "socket",
        lambda family, socktype: created.append(_FakeStreamSocket(family, socktype)) or created[-1],
    )

    sender = TCPSender(host="2001:db8::1", port=9060)
    try:
        assert sender.send(_packet()) is True
        assert created[0].family == socket.AF_INET6
    finally:
        sender.close()


def test_tcp_sender_resolves_hostname_via_getaddrinfo(monkeypatch):
    calls = []

    def fake_getaddrinfo(host, port, *args, **kwargs):
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.5", port))]

    created: list[_FakeStreamSocket] = []

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda family, socktype: created.append(_FakeStreamSocket(family, socktype)) or created[-1],
    )

    sender = TCPSender(host="homer.example.invalid", port=9060)
    try:
        assert sender.send(_packet()) is True
        assert "homer.example.invalid" in calls
        assert created[0].connected_to == ("203.0.113.5", 9060)
    finally:
        sender.close()


def test_tcp_sender_connects_once_and_reuses_connection(monkeypatch):
    """Contrairement à UDP (une socket non connectée, cible passée à chaque
    sendto()), TCP ouvre une vraie connexion : elle doit être réutilisée pour
    plusieurs envois, pas rouverte à chaque paquet."""
    created: list[_FakeStreamSocket] = []
    monkeypatch.setattr(
        socket,
        "socket",
        lambda family, socktype: created.append(_FakeStreamSocket(family, socktype)) or created[-1],
    )

    sender = TCPSender(host="192.0.2.10", port=9060)
    try:
        assert sender.send(_packet()) is True
        assert sender.send(_packet()) is True
        assert len(created) == 1
        assert len(created[0].sent) == 2
        assert all(chunk.startswith(b"HEP3") for chunk in created[0].sent)
    finally:
        sender.close()


def test_tcp_sender_sets_tcp_nodelay_on_connect(monkeypatch):
    """`_connect()` doit désactiver l'algorithme de Nagle sur la socket brute,
    une seule fois, à la connexion — pas à chaque envoi (voir aussi
    `test_tcp_sender_connects_once_and_reuses_connection`)."""
    created: list[_FakeStreamSocket] = []
    monkeypatch.setattr(
        socket,
        "socket",
        lambda family, socktype: created.append(_FakeStreamSocket(family, socktype)) or created[-1],
    )

    sender = TCPSender(host="192.0.2.10", port=9060)
    try:
        assert sender.send(_packet()) is True
        assert sender.send(_packet()) is True
        assert len(created) == 1
        assert created[0].sockopts == [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]
    finally:
        sender.close()


def test_tcp_sender_sets_tcp_nodelay_before_tls_wrap(monkeypatch):
    """`TCP_NODELAY` est une option de la socket TCP brute : elle doit être
    positionnée avant l'enrobage TLS, sur `raw_sock` et non sur le futur
    `ssl.SSLSocket` — sans quoi `setsockopt()` s'appliquerait au mauvais
    objet une fois `context.wrap_socket()` appelé."""
    monkeypatch.setattr(socket, "socket", _FakeStreamSocket)
    monkeypatch.setattr(
        ssl.SSLContext,
        "wrap_socket",
        lambda self, sock, server_hostname=None: sock,  # pas de vrai enrobage ici
    )

    sender = TCPSender(host="homer.example.invalid", port=9060, tls=True, tls_verify=False)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.5", port))
        ],
    )
    try:
        assert sender.send(_packet()) is True
        assert isinstance(sender._sock, _FakeStreamSocket)
        assert sender._sock.sockopts == [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]
    finally:
        sender.close()


def test_tcp_sender_resolution_failure_returns_false(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        raise socket.gaierror("nom introuvable")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    sender = TCPSender(host="ne-resout-pas.invalid", port=9060)
    assert sender.send(_packet()) is False
    assert sender._sock is None


def test_tcp_sender_connect_failure_closes_partial_socket(monkeypatch):
    """Si connect() échoue, la socket déjà créée doit être fermée plutôt que
    de fuir un descripteur — sender._sock ne doit pas non plus rester sur un
    objet à moitié connecté."""

    class RefusingSocket(_FakeStreamSocket):
        def connect(self, addr):
            raise ConnectionRefusedError("connexion refusée")

    created: list[RefusingSocket] = []
    monkeypatch.setattr(
        socket,
        "socket",
        lambda family, socktype: created.append(RefusingSocket(family, socktype)) or created[-1],
    )

    sender = TCPSender(host="192.0.2.10", port=9060)
    assert sender.send(_packet()) is False
    assert sender._sock is None
    assert created[0].closed is True


def test_tcp_sender_send_failure_resets_socket_for_retry(monkeypatch):
    class BoomSocket(_FakeStreamSocket):
        def sendall(self, data):
            raise OSError("connexion réinitialisée par le pair")

    monkeypatch.setattr(socket, "socket", BoomSocket)

    sender = TCPSender(host="192.0.2.10", port=9060)
    assert sender.send(_packet()) is False
    assert sender._sock is None


def test_tcp_sender_close_is_idempotent(monkeypatch):
    monkeypatch.setattr(socket, "socket", _FakeStreamSocket)
    sender = TCPSender(host="127.0.0.1", port=9060)
    sender.send(_packet())
    sender.close()
    assert sender._sock is None
    sender.close()  # ne doit pas lever
    assert sender._sock is None


# --- TCPSender : construction du contexte TLS --------------------------------


def test_tls_context_verify_true_uses_secure_defaults():
    sender = TCPSender(host="homer.example.invalid", port=9060, tls=True, tls_verify=True)
    context = sender._build_tls_context()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_tls_context_verify_true_passes_custom_ca_file(monkeypatch):
    captured = {}

    def fake_create_default_context(cafile=None):
        captured["cafile"] = cafile
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(ssl, "create_default_context", fake_create_default_context)

    sender = TCPSender(
        host="homer.example.invalid",
        port=9060,
        tls=True,
        tls_verify=True,
        tls_ca_file="/etc/oxo-hep-bridge/ca.pem",
    )
    sender._build_tls_context()
    assert captured["cafile"] == "/etc/oxo-hep-bridge/ca.pem"


def test_tls_context_insecure_disables_verification():
    sender = TCPSender(host="homer.example.invalid", port=9060, tls=True, tls_verify=False)
    context = sender._build_tls_context()
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_tls_context_insecure_still_loads_custom_ca_file(monkeypatch):
    """Même non vérifié, un fichier CA explicite reste chargé dans le
    contexte (peut servir à d'autres usages du contexte) — mock de
    `load_verify_locations` pour ne pas dépendre d'un vrai fichier PEM."""
    calls = []
    monkeypatch.setattr(
        ssl.SSLContext,
        "load_verify_locations",
        lambda self, cafile=None, **kw: calls.append(cafile),
    )

    sender = TCPSender(
        host="homer.example.invalid",
        port=9060,
        tls=True,
        tls_verify=False,
        tls_ca_file="/etc/oxo-hep-bridge/ca.pem",
    )
    context = sender._build_tls_context()
    assert calls == ["/etc/oxo-hep-bridge/ca.pem"]
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_tls_context_insecure_without_ca_file_skips_load(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ssl.SSLContext,
        "load_verify_locations",
        lambda self, cafile=None, **kw: calls.append(cafile),
    )

    sender = TCPSender(host="homer.example.invalid", port=9060, tls=True, tls_verify=False)
    sender._build_tls_context()
    assert calls == []


# --- TCPSender : envoi sous TLS ----------------------------------------------


def test_tcp_sender_wraps_socket_with_tls_and_sends(monkeypatch):
    wrap_calls = []

    class FakeTLSSocket:
        def __init__(self, raw, server_hostname):
            self.raw = raw
            self.server_hostname = server_hostname
            self.sent: list[bytes] = []
            wrap_calls.append(server_hostname)

        def sendall(self, data):
            self.sent.append(data)

        def close(self):
            self.raw.close()

    monkeypatch.setattr(socket, "socket", _FakeStreamSocket)
    monkeypatch.setattr(
        ssl.SSLContext,
        "wrap_socket",
        lambda self, sock, server_hostname=None: FakeTLSSocket(sock, server_hostname),
    )

    sender = TCPSender(host="homer.example.invalid", port=9060, tls=True, tls_verify=False)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.5", port))
        ],
    )
    try:
        assert sender.send(_packet()) is True
        assert wrap_calls == ["homer.example.invalid"]
        assert isinstance(sender._sock, FakeTLSSocket)
        assert len(sender._sock.sent) == 1
        assert sender._sock.sent[0].startswith(b"HEP3")
    finally:
        sender.close()


def test_tcp_sender_tls_handshake_failure_resets_and_returns_false(monkeypatch):
    created: list[_FakeStreamSocket] = []

    def fake_socket_ctor(family, socktype):
        sock = _FakeStreamSocket(family, socktype)
        created.append(sock)
        return sock

    def boom_wrap(self, sock, server_hostname=None):
        raise ssl.SSLCertVerificationError("certificat invalide")

    monkeypatch.setattr(socket, "socket", fake_socket_ctor)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", boom_wrap)

    sender = TCPSender(host="192.0.2.10", port=9060, tls=True, tls_verify=True)
    assert sender.send(_packet()) is False
    assert sender._sock is None
    # la socket TCP brute, ouverte avant l'échec de la poignée de main TLS,
    # ne doit pas fuir : _connect() doit l'avoir refermée.
    assert created[0].closed is True


@pytest.mark.parametrize(
    ("dry_run", "expected_type"),
    [(True, NullSender), (False, UDPSender)],
)
def test_make_sender_respects_dry_run(dry_run, expected_type):
    sender = make_sender(host="127.0.0.1", port=9060, dry_run=dry_run)
    assert isinstance(sender, expected_type)
    if isinstance(sender, UDPSender):
        sender.close()


@pytest.mark.parametrize(
    ("transport", "expected_tls"),
    [("tcp", False), ("tls", True)],
)
def test_make_sender_returns_tcp_sender_for_stream_transports(transport, expected_tls):
    sender = make_sender(host="127.0.0.1", port=9060, transport=transport)
    try:
        assert isinstance(sender, TCPSender)
        assert sender.tls is expected_tls
    finally:
        sender.close()


def test_make_sender_forwards_tls_options():
    sender = make_sender(
        host="127.0.0.1",
        port=9060,
        transport="tls",
        tls_verify=False,
        tls_ca_file="/etc/oxo-hep-bridge/ca.pem",
    )
    try:
        assert sender.tls_verify is False
        assert sender.tls_ca_file == "/etc/oxo-hep-bridge/ca.pem"
    finally:
        sender.close()


def test_make_sender_dry_run_ignores_transport():
    """dry_run doit toujours primer : même transport="tls" ne doit pas
    empêcher le court-circuit vers NullSender (le dry-run ne valide que
    l'encodage, jamais le transport réseau)."""
    sender = make_sender(host="127.0.0.1", port=9060, dry_run=True, transport="tls")
    assert isinstance(sender, NullSender)


def test_make_sender_rejects_unknown_transport():
    with pytest.raises(ValueError, match="transport HEP inconnu"):
        make_sender(host="127.0.0.1", port=9060, transport="quic")


# --- compress_payload : propagation jusqu'à l'octet envoyé sur le fil -------


def test_null_sender_compress_true_encodes_compressed_chunk():
    """NullSender (dry-run) doit lui aussi respecter `compress` — le dry-run
    sert justement à valider l'encodage, compression comprise, sans réseau."""
    sender = NullSender(compress=True)
    assert sender.send(_packet()) is True


def test_udp_sender_compress_true_sends_compressed_payload_chunk(monkeypatch):
    """Le paquet réellement envoyé sur la socket UDP doit porter le chunk
    COMPRESSED_PAYLOAD (0x0010), pas PAYLOAD (0x000F), quand compress=True."""
    sent: list[bytes] = []

    class FakeDgramSocket:
        def __init__(self, family, socktype):
            pass

        def connect(self, addr):
            pass

        def sendto(self, data, addr):
            sent.append(data)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", FakeDgramSocket)

    sender = UDPSender(host="192.0.2.10", port=9060, compress=True)
    try:
        assert sender.send(_packet()) is True
    finally:
        sender.close()

    assert len(sent) == 1
    chunks = decode(sent[0])
    types = [ct for _, ct, _ in chunks]
    assert ChunkType.COMPRESSED_PAYLOAD in types
    assert ChunkType.PAYLOAD not in types
    by_type = {ct: payload for _, ct, payload in chunks}
    assert gzip.decompress(by_type[ChunkType.COMPRESSED_PAYLOAD]) == b'{"x":1}'


def test_udp_sender_compress_false_by_default_sends_plain_payload_chunk(monkeypatch):
    sent: list[bytes] = []

    class FakeDgramSocket:
        def __init__(self, family, socktype):
            pass

        def connect(self, addr):
            pass

        def sendto(self, data, addr):
            sent.append(data)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", FakeDgramSocket)

    sender = UDPSender(host="192.0.2.10", port=9060)
    try:
        sender.send(_packet())
    finally:
        sender.close()

    types = [ct for _, ct, _ in decode(sent[0])]
    assert ChunkType.PAYLOAD in types
    assert ChunkType.COMPRESSED_PAYLOAD not in types


def test_tcp_sender_compress_true_sends_compressed_payload_chunk(monkeypatch):
    monkeypatch.setattr(socket, "socket", _FakeStreamSocket)

    sender = TCPSender(host="192.0.2.10", port=9060, compress=True)
    try:
        assert sender.send(_packet()) is True
        chunks = decode(sender._sock.sent[0])
    finally:
        sender.close()

    types = [ct for _, ct, _ in chunks]
    assert ChunkType.COMPRESSED_PAYLOAD in types
    assert ChunkType.PAYLOAD not in types


def test_make_sender_forwards_compress_to_null_sender():
    sender = make_sender(host="127.0.0.1", port=9060, dry_run=True, compress=True)
    assert isinstance(sender, NullSender)
    assert sender.compress is True


def test_make_sender_forwards_compress_to_udp_sender():
    sender = make_sender(host="127.0.0.1", port=9060, compress=True)
    try:
        assert isinstance(sender, UDPSender)
        assert sender.compress is True
    finally:
        sender.close()


def test_make_sender_forwards_compress_to_tcp_sender():
    sender = make_sender(host="127.0.0.1", port=9060, transport="tcp", compress=True)
    try:
        assert isinstance(sender, TCPSender)
        assert sender.compress is True
    finally:
        sender.close()


def test_make_sender_compress_defaults_to_false():
    sender = make_sender(host="127.0.0.1", port=9060)
    try:
        assert sender.compress is False
    finally:
        sender.close()


# --- Retry/backoff sur échec d'envoi (--hep-retries/--hep-retry-backoff) -----


class _FlakyDgramSocket:
    """Socket UDP factice qui échoue sur les `fail_first_n` premiers envois,
    puis réussit — simule une coupure réseau brève qui se résorbe."""

    def __init__(self, fail_first_n: int) -> None:
        self.fail_first_n = fail_first_n
        self.attempts = 0
        self.sent: list[bytes] = []

    def connect(self, addr):
        pass

    def sendto(self, data, addr):
        self.attempts += 1
        if self.attempts <= self.fail_first_n:
            raise OSError("réseau injoignable (transitoire)")
        self.sent.append(data)

    def close(self):
        pass


def test_udp_sender_retries_zero_by_default_fails_immediately(monkeypatch):
    """Comportement historique inchangé : sans --hep-retries, un seul essai,
    aucun sleep."""
    sleeps: list[float] = []
    monkeypatch.setattr(
        socket, "socket", lambda family, socktype: _FlakyDgramSocket(fail_first_n=1)
    )
    sender = UDPSender(host="192.0.2.10", port=9060, sleep=sleeps.append)
    assert sender.send(_packet()) is False
    assert sleeps == []
    assert sender.retry_count == 0


def test_udp_sender_retries_until_success(monkeypatch):
    """2 échecs puis un succès, avec retries=3 : le paquet doit finir par
    partir, avec 2 tentatives supplémentaires consommées."""
    flaky = _FlakyDgramSocket(fail_first_n=2)
    monkeypatch.setattr(socket, "socket", lambda family, socktype: flaky)
    sleeps: list[float] = []
    sender = UDPSender(
        host="192.0.2.10", port=9060, retries=3, retry_backoff=0.1, sleep=sleeps.append
    )
    assert sender.send(_packet()) is True
    assert len(flaky.sent) == 1
    assert flaky.attempts == 3
    assert sender.retry_count == 2
    # backoff exponentiel : 0.1s puis 0.2s entre les 3 tentatives
    assert sleeps == [0.1, 0.2]


def test_udp_sender_retries_exhausted_returns_false(monkeypatch):
    """Échec permanent (collecteur injoignable) : toutes les tentatives sont
    consommées puis l'envoi finit par échouer."""
    flaky = _FlakyDgramSocket(fail_first_n=99)
    monkeypatch.setattr(socket, "socket", lambda family, socktype: flaky)
    sleeps: list[float] = []
    sender = UDPSender(
        host="192.0.2.10", port=9060, retries=2, retry_backoff=0.05, sleep=sleeps.append
    )
    assert sender.send(_packet()) is False
    # 1 essai initial + 2 retries = 3 tentatives au total
    assert flaky.attempts == 3
    assert sender.retry_count == 2
    assert sleeps == [0.05, 0.1]


def test_udp_sender_retry_count_accumulates_across_sends(monkeypatch):
    """`retry_count` est cumulé sur la durée de vie du sender (utile pour les
    stats de fin de run), pas remis à zéro entre deux paquets."""
    flaky = _FlakyDgramSocket(fail_first_n=1)
    monkeypatch.setattr(socket, "socket", lambda family, socktype: flaky)
    sender = UDPSender(
        host="192.0.2.10", port=9060, retries=1, retry_backoff=0.01, sleep=lambda d: None
    )
    assert sender.send(_packet()) is True  # 1 retry consommé
    assert sender.retry_count == 1
    assert sender.send(_packet()) is True  # aucun nouvel échec, pas de retry
    assert sender.retry_count == 1


class _FlakyStreamSocket(_FakeStreamSocket):
    """Socket TCP factice qui échoue sur les `fail_first_n` premiers `sendall`."""

    def __init__(self, fail_first_n: int, *a, **kw):
        super().__init__(*a, **kw)
        self.fail_first_n = fail_first_n
        self.attempts = 0

    def sendall(self, data):
        self.attempts += 1
        if self.attempts <= self.fail_first_n:
            raise OSError("connexion réinitialisée (transitoire)")
        self.sent.append(data)


def test_tcp_sender_retries_until_success(monkeypatch):
    flaky = _FlakyStreamSocket(fail_first_n=1)
    monkeypatch.setattr(socket, "socket", lambda family, socktype: flaky)
    sleeps: list[float] = []
    sender = TCPSender(
        host="192.0.2.10", port=9060, retries=2, retry_backoff=0.2, sleep=sleeps.append
    )
    try:
        assert sender.send(_packet()) is True
        assert flaky.attempts == 2
        assert sender.retry_count == 1
        assert sleeps == [0.2]
    finally:
        sender.close()


def test_tcp_sender_retries_exhausted_returns_false(monkeypatch):
    flaky = _FlakyStreamSocket(fail_first_n=99)
    monkeypatch.setattr(socket, "socket", lambda family, socktype: flaky)
    sender = TCPSender(
        host="192.0.2.10", port=9060, retries=1, retry_backoff=0.01, sleep=lambda d: None
    )
    assert sender.send(_packet()) is False
    assert flaky.attempts == 2
    assert sender.retry_count == 1


def test_null_sender_ignores_retries_never_fails():
    """dry-run ne peut pas échouer : make_sender() ne doit pas planter même
    si retries/retry_backoff sont positionnés."""
    sender = make_sender(host="127.0.0.1", port=9060, dry_run=True, retries=5, retry_backoff=1.0)
    assert isinstance(sender, NullSender)
    assert sender.send(_packet()) is True


def test_make_sender_forwards_retries_to_udp_sender():
    sender = make_sender(host="127.0.0.1", port=9060, retries=4, retry_backoff=0.25)
    try:
        assert isinstance(sender, UDPSender)
        assert sender.retries == 4
        assert sender.retry_backoff == 0.25
    finally:
        sender.close()


def test_make_sender_forwards_retries_to_tcp_sender():
    sender = make_sender(
        host="127.0.0.1", port=9060, transport="tcp", retries=4, retry_backoff=0.25
    )
    try:
        assert isinstance(sender, TCPSender)
        assert sender.retries == 4
        assert sender.retry_backoff == 0.25
    finally:
        sender.close()


def test_make_sender_retries_default_to_zero():
    sender = make_sender(host="127.0.0.1", port=9060)
    try:
        assert sender.retries == 0
        assert sender.retry_backoff == 0.5
    finally:
        sender.close()


# --- Constats d'audit (session 39) et suites (sessions 40, 41) -------------
#
# Les tests ci-dessous utilisent de vraies sockets loopback (pas de mock) :
# leur but est de vérifier, empiriquement, un comportement RÉSEAU réel du
# noyau — pas seulement le routage interne déjà couvert par les tests
# mockés ci-dessus. Les deux candidats du backlog (UDPSender.connect() en
# session 40, TCPSender/TCP_NODELAY en session 41) sont désormais
# implémentés ; les deux tests ci-dessous vérifient le comportement
# CORRIGÉ, pas un défaut à préserver.


def test_udp_sender_connect_detects_closed_remote_port_on_second_send():
    """Fonctionnalité implémentée en session 40 (candidat #1 de
    docs/roadmap.md) : `_connect()` appelle désormais `sock.connect()` en
    plus de créer la socket — l'envoi lui-même reste `sendto()`, inchangé
    (vérifié empiriquement qu'une socket connectée continue de remonter
    l'ICMP même via `sendto()` plutôt que `send()`, voir session 40).

    Sur un port UDP fermé garanti (bind()+close() immédiat), le premier
    envoi réussit encore : l'ICMP « port unreachable » n'a pas encore eu le
    temps de revenir. C'est le deuxième envoi qui échoue, une fois cet ICMP
    traité par le noyau pour cette socket connectée — caractéristique
    inhérente à UDP/ICMP (livraison asynchrone), pas une limite de cette
    implémentation : un run réel qui perd son collecteur ne le détectera
    donc qu'à partir du deuxième paquet suivant la coupure, pas
    instantanément. Voir docs/architecture.md#transport-hep--udp-tcp-tls.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()  # le port est maintenant garanti fermé (personne n'écoute)

    sender = UDPSender(host="127.0.0.1", port=closed_port)
    try:
        assert sender.send(_packet()) is True  # ICMP pas encore revenu
        time.sleep(0.2)  # laisse le temps à l'ICMP unreachable de revenir
        assert sender.send(_packet()) is False  # détecté cette fois
    finally:
        sender.close()


def test_tcp_sender_nodelay_active_on_real_loopback_socket():
    """Fonctionnalité implémentée en session 41 (dernier candidat de
    docs/roadmap.md) : `_connect()` appelle désormais
    `setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)` juste après `connect()`, sur
    une vraie socket TCP loopback (pas un mock) — vérifie que l'option est
    effectivement acceptée et lue par le noyau, pas seulement que l'appel a
    eu lieu (déjà couvert côté mock par
    `test_tcp_sender_sets_tcp_nodelay_on_connect`).

    Le listener réel (sans appel à `accept()`) suffit : la poignée de main
    TCP se termine dès l'acceptation dans le backlog du noyau, avant même
    qu'une application n'appelle `accept()`.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        sender = TCPSender(host="127.0.0.1", port=port)
        try:
            assert sender.send(_packet()) is True
            assert sender._sock is not None
            nodelay = sender._sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
            assert nodelay != 0
        finally:
            sender.close()
    finally:
        listener.close()
