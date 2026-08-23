from __future__ import annotations

import tempfile
from pathlib import Path

from nova_ai.tools.cisco_packet_tracer import CiscoPacketTracerTool


def test_cisco_multi_router_ospf() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tool = CiscoPacketTracerTool()
        result = tool.execute(
            project_name="Test_Lab",
            topology_type="multi_router_ospf",
            output_dir=tmpdir,
        )
        assert result.success is True
        assert "Multi-Router OSPF" in result.content

        out_path = Path(tmpdir)
        assert (out_path / "R1_HQ.cfg").exists()
        assert (out_path / "R2_Branch.cfg").exists()
        assert (out_path / "SW1_HQ.cfg").exists()
        assert (out_path / "README_TOPOLOGY.md").exists()

        r1_content = (out_path / "R1_HQ.cfg").read_text()
        assert "hostname R1-HQ" in r1_content
        assert "router ospf 1" in r1_content
        assert "router-id 1.1.1.1" in r1_content


def test_cisco_router_on_a_stick() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tool = CiscoPacketTracerTool()
        result = tool.execute(
            project_name="ROAS_Lab",
            topology_type="router_on_a_stick",
            output_dir=tmpdir,
        )
        assert result.success is True
        assert "Router-on-a-Stick" in result.content

        out_path = Path(tmpdir)
        r1 = (out_path / "R1_Gateway.cfg").read_text()
        assert "encapsulation dot1Q 10" in r1
        assert "GigabitEthernet0/0/0.10" in r1

        sw1 = (out_path / "SW1_Access.cfg").read_text()
        assert "switchport mode trunk" in sw1
        assert "switchport mode access" in sw1


def test_cisco_branch_office_wan() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tool = CiscoPacketTracerTool()
        result = tool.execute(
            project_name="WAN_Lab", topology_type="branch_office_wan", output_dir=tmpdir
        )
        assert result.success is True
        assert "Branch Office WAN" in result.content

        out_path = Path(tmpdir)
        assert (out_path / "R1_HQ.cfg").exists()
        assert (out_path / "R2_Branch_A.cfg").exists()
        assert (out_path / "R3_Branch_B.cfg").exists()


def test_cisco_campus_lan() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tool = CiscoPacketTracerTool()
        result = tool.execute(
            project_name="Campus", topology_type="campus_lan", output_dir=tmpdir
        )
        assert result.success is True
        assert "Campus LAN" in result.content


def test_cisco_invalid_topology() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tool = CiscoPacketTracerTool()
        result = tool.execute(
            project_name="Bad", topology_type="nonexistent", output_dir=tmpdir
        )
        assert result.success is False
        assert "Unknown topology" in result.content
