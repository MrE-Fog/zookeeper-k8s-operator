# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness
from pytest_mock import MockerFixture

from charm import ZookeeperK8sCharm


@pytest.fixture
def harness():
    zookeeper_harness = Harness(ZookeeperK8sCharm)
    zookeeper_harness.begin()
    yield zookeeper_harness
    zookeeper_harness.cleanup()


def test_on_config_changed(mocker: MockerFixture, harness: Harness):
    # test config validation
    _validate_config_original = harness.charm._validate_config
    harness.charm._validate_config = mocker.Mock()
    harness.charm._validate_config.side_effect = [Exception()]
    harness.charm.on.config_changed.emit()
    assert harness.charm.unit.status == BlockedStatus("")
    harness.charm._validate_config = _validate_config_original
    # test pebble not ready
    harness.charm.unit.get_container("zookeeper").can_connect = mocker.Mock()
    harness.charm.unit.get_container("zookeeper").can_connect.side_effect = [False, True, True]
    harness.charm.on.config_changed.emit()
    assert harness.charm.unit.status == MaintenanceStatus("waiting for pebble to start")
    # test pebble ready
    spy = mocker.spy(harness.charm.unit.get_container("zookeeper"), "replan")
    harness.charm.on.zookeeper_pebble_ready.emit("zookeeper")
    assert harness.charm.unit.status == ActiveStatus()
    assert spy.call_count == 1


def test_on_update_status(mocker: MockerFixture, harness: Harness):
    # Make sure the service zookeeper is set
    harness.charm.on.zookeeper_pebble_ready.emit("zookeeper")
    harness.charm.unit.get_container("zookeeper").can_connect = mocker.Mock()
    harness.charm.unit.get_container("zookeeper").can_connect.side_effect = [
        False,
        True,
        True,
        True,
    ]
    # test service not ready
    original_get_plan = harness.charm.unit.get_container("zookeeper").get_plan
    harness.charm.unit.get_container("zookeeper").get_plan = mocker.Mock()
    harness.charm.unit.get_container("zookeeper").get_plan().services = {}
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == WaitingStatus("zookeeper service not configured yet")
    harness.charm.unit.get_container("zookeeper").get_plan = original_get_plan
    # test service not running
    harness.charm.unit.get_container("zookeeper").stop("zookeeper")
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == BlockedStatus("zookeeper service is not running")
    # test service running
    harness.charm.unit.get_container("zookeeper").start("zookeeper")
    harness.charm.on.zookeeper_pebble_ready.emit("zookeeper")
    assert harness.charm.unit.status == ActiveStatus()


def test_scaling(mocker: MockerFixture, harness: Harness):
    # Set current unit the leader
    harness.set_leader(True)
    # Add remote unit
    remote_unit = f"{harness.charm.app.name}/1"
    relation_id = harness.add_relation("cluster", harness.charm.app.name)
    harness.add_relation_unit(relation_id, remote_unit)
    harness.update_relation_data(
        relation_id,
        remote_unit,
        {"host": "zookeeper-1", "server-port": "2888", "election-port": "3888"},
    )
    # Register current unit
    harness.charm.cluster.register_server(host="zookeeper-0", server_port=2888, election_port=3888)

    assert ["zookeeper-0:2888:3888", "zookeeper-1:2888:3888"] == harness.charm.cluster.servers