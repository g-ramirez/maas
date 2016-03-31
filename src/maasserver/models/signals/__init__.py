# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Signals coming off models."""

__all__ = [
    "bmc",
    "config",
    "events",
    "interfaces",
    "nodes",
    "power",
    "services",
    "staticipaddress",
]

from maasserver.models.signals import (
    bmc,
    config,
    events,
    interfaces,
    nodes,
    power,
    services,
    staticipaddress,
)
