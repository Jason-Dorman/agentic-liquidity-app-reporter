"""Shared test setup: every test runs with the network cut off (T-21, Q16)."""

import socket

import pytest


def _refuse(*_args, **_kwargs):
    raise RuntimeError("tests never touch the network (T-21); use a fake")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Make every socket connection and name lookup raise, so a test that reaches out fails."""
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
