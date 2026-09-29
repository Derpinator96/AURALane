"""boto3 clients built the same way everywhere: a pool of 32 connections, TCP
keep-alive, standard retries.

The API builds each provider once per process, so each provider's client is that
process's one client for the service (clients are thread safe and hold the
connection pool). Nothing is cached here on purpose: a module-level cache would
outlive a test's moto context and send the next test's calls to real AWS.
"""
from __future__ import annotations

import boto3
from botocore.config import Config

from core.providers.aws.config import REGION


def session(region: str = REGION) -> boto3.Session:
    return boto3.Session(region_name=region)


def config(**extra) -> Config:
    return Config(max_pool_connections=32, tcp_keepalive=True, connect_timeout=5, read_timeout=60,
                  retries={"max_attempts": 3, "mode": "standard"}, **extra)


def client(service: str, region: str = REGION, **config_extra):
    return boto3.client(service, region_name=region, config=config(**config_extra))
