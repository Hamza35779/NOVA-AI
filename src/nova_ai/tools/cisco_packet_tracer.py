"""Cisco Packet Tracer Network Demo Generator tool.

Generates complete Cisco network topology designs, router/switch startup configuration
files (.cfg), subnet allocation tables, and packet tracer simulation test scripts.
Supports: Router-on-a-Stick, Multi-Router OSPF, Branch Office WAN, Campus LAN.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from nova_ai.core.paths import get_config_dir
from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_\- ]")


def _router_config(
    hostname: str,
    interfaces: List[Dict[str, str]],
    routing: str = "ospf 1",
    networks: Optional[List[str]] = None,
    dhcp_pools: Optional[List[Dict[str, str]]] = None,
    subinterfaces: Optional[List[Dict[str, str]]] = None,
    router_id: Optional[str] = None,
    static_routes: Optional[List[str]] = None,
) -> str:
    """Generate Cisco IOS Router startup configuration."""
    lines = [
        f"hostname {hostname}",
        "no ip domain-lookup",
        "service password-encryption",
        "enable secret class",
        "line con 0",
        " password cisco",
        " logging synchronous",
        " login",
        "line vty 0 4",
        " password cisco",
        " login",
        " transport input ssh telnet",
        "exit",
        "!",
    ]

    # DHCP pools
    for pool in dhcp_pools or []:
        gateway = pool.get("gateway", "")
        lines.extend(
            [
                f"ip dhcp excluded-address {gateway}",
                f"ip dhcp pool {pool.get('name', 'POOL')}",
                f" network {pool.get('network', '')}",
                f" default-router {gateway}",
                f" dns-server {pool.get('dns', '8.8.8.8')}",
                "exit",
                "!",
            ]
        )

    # Physical interfaces
    for iface in interfaces:
        lines.extend(
            [
                f"interface {iface['name']}",
                f" description {iface.get('desc', '')}",
                f" ip address {iface['ip']} {iface['mask']}",
                " no shutdown",
                "exit",
                "!",
            ]
        )

    # Sub-interfaces (Router-on-a-Stick)
    for sub in subinterfaces or []:
        lines.extend(
            [
                f"interface {sub['name']}",
                f" description {sub.get('desc', 'VLAN Trunk')}",
                f" encapsulation dot1Q {sub['vlan']}",
                f" ip address {sub['ip']} {sub['mask']}",
                "exit",
                "!",
            ]
        )

    # Routing protocol
    if networks:
        lines.append(f"router {routing}")
        if router_id:
            lines.append(f" router-id {router_id}")
        for net in networks:
            lines.append(f" network {net}")
        lines.extend(["exit", "!"])

    # Static routes
    for route in static_routes or []:
        lines.append(f"ip route {route}")

    lines.extend(
        [
            "banner motd # Authorized Access Only - NOVA AI Network Demo #",
            "end",
            "write memory",
        ]
    )
    return "\n".join(lines)


def _switch_config(
    hostname: str,
    vlans: List[Dict[str, Any]],
    trunk_ports: Optional[List[Dict[str, str]]] = None,
    access_ports: Optional[List[Dict[str, str]]] = None,
    mgmt_vlan: str = "1",
    mgmt_ip: str = "192.168.1.2",
    mgmt_mask: str = "255.255.255.0",
    default_gw: str = "192.168.1.1",
    stp_mode: str = "rapid-pvst",
) -> str:
    """Generate Cisco Catalyst Switch configuration with VLANs, trunks, and access ports."""
    lines = [
        f"hostname {hostname}",
        "no ip domain-lookup",
        "enable secret class",
        f"spanning-tree mode {stp_mode}",
        "!",
    ]

    for vlan in vlans:
        vid = vlan.get("id", "10")
        lines.extend(
            [f"vlan {vid}", f" name {vlan.get('name', f'VLAN_{vid}')}", "exit"]
        )

    lines.append("!")

    # Trunk ports
    for tp in trunk_ports or []:
        lines.extend(
            [
                f"interface {tp['port']}",
                " switchport mode trunk",
                f" switchport trunk native vlan {tp.get('native', '99')}",
                f" switchport trunk allowed vlan {tp.get('allowed', 'all')}",
                " no shutdown",
                "exit",
            ]
        )

    # Access ports
    for ap in access_ports or []:
        lines.extend(
            [
                f"interface {ap['port']}",
                " switchport mode access",
                f" switchport access vlan {ap['vlan']}",
                " spanning-tree portfast",
                " no shutdown",
                "exit",
            ]
        )

    lines.extend(
        [
            "!",
            f"interface vlan {mgmt_vlan}",
            f" ip address {mgmt_ip} {mgmt_mask}",
            " no shutdown",
            "exit",
            f"ip default-gateway {default_gw}",
            "!",
            "line con 0",
            " password cisco",
            " login",
            "line vty 0 15",
            " password cisco",
            " login",
            "!",
            "end",
            "write memory",
        ]
    )
    return "\n".join(lines)


# ── Topology Generators ────────────────────────────────────────


def _topo_multi_router_ospf(target: Path) -> List[str]:
    """Standard dual-router OSPF topology with DHCP."""
    files = []

    cfg = _router_config(
        hostname="R1-HQ",
        interfaces=[
            {
                "name": "GigabitEthernet0/0/0",
                "ip": "192.168.10.1",
                "mask": "255.255.255.0",
                "desc": "HQ Staff LAN",
            },
            {
                "name": "GigabitEthernet0/0/1",
                "ip": "10.0.0.1",
                "mask": "255.255.255.252",
                "desc": "WAN to Branch",
            },
        ],
        routing="ospf 1",
        router_id="1.1.1.1",
        networks=["192.168.10.0 0.0.0.255 area 0", "10.0.0.0 0.0.0.3 area 0"],
        dhcp_pools=[
            {
                "name": "HQ_POOL",
                "network": "192.168.10.0 255.255.255.0",
                "gateway": "192.168.10.1",
            }
        ],
    )
    (target / "R1_HQ.cfg").write_text(cfg, encoding="utf-8")
    files.append("R1_HQ.cfg")

    cfg = _router_config(
        hostname="R2-Branch",
        interfaces=[
            {
                "name": "GigabitEthernet0/0/0",
                "ip": "192.168.20.1",
                "mask": "255.255.255.0",
                "desc": "Branch LAN",
            },
            {
                "name": "GigabitEthernet0/0/1",
                "ip": "10.0.0.2",
                "mask": "255.255.255.252",
                "desc": "WAN to HQ",
            },
        ],
        routing="ospf 1",
        router_id="2.2.2.2",
        networks=["192.168.20.0 0.0.0.255 area 0", "10.0.0.0 0.0.0.3 area 0"],
        dhcp_pools=[
            {
                "name": "BRANCH_POOL",
                "network": "192.168.20.0 255.255.255.0",
                "gateway": "192.168.20.1",
            }
        ],
    )
    (target / "R2_Branch.cfg").write_text(cfg, encoding="utf-8")
    files.append("R2_Branch.cfg")

    cfg = _switch_config(
        hostname="SW1-HQ",
        vlans=[
            {"id": "10", "name": "Staff"},
            {"id": "20", "name": "Mgmt"},
            {"id": "99", "name": "Native"},
        ],
        trunk_ports=[{"port": "GigabitEthernet0/1", "native": "99"}],
        access_ports=[
            {"port": "FastEthernet0/1", "vlan": "10"},
            {"port": "FastEthernet0/2", "vlan": "10"},
        ],
        mgmt_ip="192.168.10.2",
        default_gw="192.168.10.1",
    )
    (target / "SW1_HQ.cfg").write_text(cfg, encoding="utf-8")
    files.append("SW1_HQ.cfg")

    return files


def _topo_router_on_a_stick(target: Path) -> List[str]:
    """Inter-VLAN routing via sub-interfaces on a single router."""
    files = []

    cfg = _router_config(
        hostname="R1-Gateway",
        interfaces=[
            {
                "name": "GigabitEthernet0/0/0",
                "ip": "unassigned",
                "mask": "255.255.255.0",
                "desc": "Trunk to SW1",
            },
        ],
        subinterfaces=[
            {
                "name": "GigabitEthernet0/0/0.10",
                "vlan": "10",
                "ip": "192.168.10.1",
                "mask": "255.255.255.0",
                "desc": "VLAN 10 Gateway",
            },
            {
                "name": "GigabitEthernet0/0/0.20",
                "vlan": "20",
                "ip": "192.168.20.1",
                "mask": "255.255.255.0",
                "desc": "VLAN 20 Gateway",
            },
            {
                "name": "GigabitEthernet0/0/0.99",
                "vlan": "99",
                "ip": "192.168.99.1",
                "mask": "255.255.255.0",
                "desc": "Native/Management",
            },
        ],
        dhcp_pools=[
            {
                "name": "VLAN10_POOL",
                "network": "192.168.10.0 255.255.255.0",
                "gateway": "192.168.10.1",
            },
            {
                "name": "VLAN20_POOL",
                "network": "192.168.20.0 255.255.255.0",
                "gateway": "192.168.20.1",
            },
        ],
    )
    (target / "R1_Gateway.cfg").write_text(cfg, encoding="utf-8")
    files.append("R1_Gateway.cfg")

    cfg = _switch_config(
        hostname="SW1-Access",
        vlans=[
            {"id": "10", "name": "Sales"},
            {"id": "20", "name": "Engineering"},
            {"id": "99", "name": "Native"},
        ],
        trunk_ports=[
            {"port": "GigabitEthernet0/1", "native": "99", "allowed": "10,20,99"}
        ],
        access_ports=[
            {"port": "FastEthernet0/1", "vlan": "10"},
            {"port": "FastEthernet0/2", "vlan": "10"},
            {"port": "FastEthernet0/3", "vlan": "20"},
            {"port": "FastEthernet0/4", "vlan": "20"},
        ],
        mgmt_vlan="99",
        mgmt_ip="192.168.99.2",
        mgmt_mask="255.255.255.0",
        default_gw="192.168.99.1",
    )
    (target / "SW1_Access.cfg").write_text(cfg, encoding="utf-8")
    files.append("SW1_Access.cfg")

    return files


def _topo_branch_office_wan(target: Path) -> List[str]:
    """Three-router WAN topology: HQ + 2 branches with serial links and EIGRP."""
    files = []

    for idx, (name, lo_ip, wan_ips, lan_ip) in enumerate(
        [
            (
                "R1-HQ",
                "1.1.1.1",
                [("Serial0/1/0", "10.0.1.1"), ("Serial0/1/1", "10.0.2.1")],
                "192.168.1.1",
            ),
            ("R2-Branch-A", "2.2.2.2", [("Serial0/1/0", "10.0.1.2")], "192.168.2.1"),
            ("R3-Branch-B", "3.3.3.3", [("Serial0/1/0", "10.0.2.2")], "192.168.3.1"),
        ],
        start=1,
    ):
        ifaces = [
            {
                "name": "GigabitEthernet0/0/0",
                "ip": lan_ip,
                "mask": "255.255.255.0",
                "desc": f"{name} LAN",
            }
        ]
        for port, ip in wan_ips:
            ifaces.append(
                {
                    "name": port,
                    "ip": ip,
                    "mask": "255.255.255.252",
                    "desc": "WAN Serial Link",
                }
            )

        cfg = _router_config(
            hostname=name,
            interfaces=ifaces,
            routing="eigrp 100",
            router_id=lo_ip,
            networks=[f"192.168.{idx}.0 0.0.0.255", "10.0.0.0 0.0.255.255"],
            dhcp_pools=[
                {
                    "name": f"LAN{idx}_POOL",
                    "network": f"192.168.{idx}.0 255.255.255.0",
                    "gateway": lan_ip,
                }
            ],
        )
        fname = f"{name.replace('-', '_')}.cfg"
        (target / fname).write_text(cfg, encoding="utf-8")
        files.append(fname)

    return files


def _topo_campus_lan(target: Path) -> List[str]:
    """Three-tier campus LAN: core, distribution, and access layer switches."""
    files = []

    core = _switch_config(
        hostname="Core-SW1",
        vlans=[
            {"id": "10", "name": "Data"},
            {"id": "20", "name": "Voice"},
            {"id": "30", "name": "Server"},
            {"id": "99", "name": "Mgmt"},
        ],
        trunk_ports=[
            {"port": "GigabitEthernet0/1", "native": "99", "allowed": "10,20,30,99"},
            {"port": "GigabitEthernet0/2", "native": "99", "allowed": "10,20,30,99"},
        ],
        mgmt_vlan="99",
        mgmt_ip="10.0.99.1",
        mgmt_mask="255.255.255.0",
        default_gw="10.0.99.254",
        stp_mode="rapid-pvst",
    )
    (target / "Core_SW1.cfg").write_text(core, encoding="utf-8")
    files.append("Core_SW1.cfg")

    for i, name in enumerate(["Dist-SW1", "Dist-SW2"], start=1):
        cfg = _switch_config(
            hostname=name,
            vlans=[
                {"id": "10", "name": "Data"},
                {"id": "20", "name": "Voice"},
                {"id": "99", "name": "Mgmt"},
            ],
            trunk_ports=[
                {"port": "GigabitEthernet0/1", "native": "99"},  # uplink to core
                {"port": "GigabitEthernet0/2", "native": "99"},  # downlink to access
            ],
            access_ports=[
                {"port": f"FastEthernet0/{j}", "vlan": "10"} for j in range(1, 5)
            ],
            mgmt_vlan="99",
            mgmt_ip=f"10.0.99.{10 + i}",
            default_gw="10.0.99.254",
        )
        fname = f"{name.replace('-', '_')}.cfg"
        (target / fname).write_text(cfg, encoding="utf-8")
        files.append(fname)

    return files


_TOPOLOGY_MAP = {
    "multi_router_ospf": (_topo_multi_router_ospf, "Multi-Router OSPF"),
    "router_on_a_stick": (_topo_router_on_a_stick, "Router-on-a-Stick Inter-VLAN"),
    "branch_office_wan": (_topo_branch_office_wan, "Branch Office WAN (EIGRP)"),
    "campus_lan": (_topo_campus_lan, "Campus LAN (3-Tier)"),
}

# Topology-specific verification steps appended to the generated README.
_TOPOLOGY_VERIFICATION: Dict[str, List[str]] = {
    "multi_router_ospf": [
        "show ip ospf neighbor          # R1 <-> R2 adjacency must be FULL",
        "show ip route ospf             # 192.168.20.0 learned via OSPF on R1",
        "show ip dhcp binding           # HQ clients received leases",
        "ping 192.168.20.1              # from an HQ PC (cross-LAN reachability)",
    ],
    "router_on_a_stick": [
        "show vlans brief               # sub-interfaces mapped to VLANs 10/20/99",
        "show interfaces trunk          # Gi0/0/1 & Gi0/1 trunking with allowed list",
        "show ip interface brief | include GigabitEthernet0/0/0.",
        "ping 192.168.10.1              # from VLAN 20 PC (inter-VLAN routing via router)",
    ],
    "branch_office_wan": [
        "show ip eigrp neighbors        # HQ sees both branch routers",
        "show ip route eigrp            # remote LANs present in routing table",
        "show controllers serial 0/1/0  # DCE/DTE cabling and clocking status",
        "ping 192.168.3.1               # HQ -> Branch-B LAN across serial WAN",
        "traceroute 192.168.2.1         # verify path via serial links",
    ],
    "campus_lan": [
        "show spanning-tree summary     # rapid-PVST active, root bridge elected",
        "show interfaces trunk          # core uplinks carry VLANs 10,20,30,99",
        "show vlan brief                # access ports assigned to Data/Voice VLANs",
        "show cdp neighbors             # core<->distribution adjacency discovery",
        "ping 10.0.99.1                 # management reachability from access switch",
    ],
}


def _generate_readme(
    project: str,
    topo_label: str,
    files: List[str],
    target: Path,
    topology_key: str = "",
) -> str:
    """Generate topology documentation with per-topology verification steps."""
    verification = _TOPOLOGY_VERIFICATION.get(topology_key, [])
    verification_block = ""
    if verification:
        verification_block = "\n".join(f"- {cmd}" for cmd in verification)

    md = f"""# Cisco Packet Tracer Demo: {project}
**Architecture:** {topo_label}

## Generated Files
{chr(10).join(f"- `{f}`" for f in files)}

## How to Import
1. Open Cisco Packet Tracer
2. Add the required routers (2911) and switches (2960-24TT)
3. Connect devices according to the topology type
4. Click each device → **CLI** → paste the matching `.cfg` file content

## Verification Commands
```
show ip interface brief
show ip route
show vlan brief
show spanning-tree summary
ping <remote-ip>
traceroute <remote-ip>
```

### Topology-Specific Checks ({topo_label})
{verification_block}
"""
    readme_path = target / "README_TOPOLOGY.md"
    readme_path.write_text(md, encoding="utf-8")
    return "README_TOPOLOGY.md"


@ToolRegistry.register("cisco_packet_tracer")
class CiscoPacketTracerTool(BaseTool):
    """Generate Cisco Packet Tracer demo packages with topology-specific configurations."""

    tool_id = "cisco_packet_tracer"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="cisco_packet_tracer",
            description=(
                "Generate complete Cisco Packet Tracer network demo configuration files. "
                "Supports 4 topology types: Router-on-a-Stick, Multi-Router OSPF, Branch Office WAN, Campus LAN. "
                "Outputs .cfg files, VLAN configs, routing configs, and documentation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Name of the network demo project.",
                    },
                    "topology_type": {
                        "type": "string",
                        "enum": list(_TOPOLOGY_MAP.keys()),
                        "description": "Network architecture pattern.",
                        "default": "multi_router_ospf",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Optional output folder path.",
                    },
                },
                "required": ["project_name"],
            },
            category="networking",
            timeout_seconds=20.0,
        )

    @track_execution("cisco_packet_tracer")
    def execute(
        self,
        project_name: str,
        topology_type: str = "multi_router_ospf",
        output_dir: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        # Sanitize project name
        clean_name = _SAFE_NAME.sub("", project_name.strip()).replace(" ", "_")
        if not clean_name:
            return ToolResult(
                tool_name="cisco_packet_tracer",
                content="Error: Invalid project name.",
                success=False,
            )

        topo_key = topology_type.lower().strip()
        entry = _TOPOLOGY_MAP.get(topo_key)
        if not entry:
            return ToolResult(
                tool_name="cisco_packet_tracer",
                content=f"Unknown topology: {topo_key}. Options: {', '.join(_TOPOLOGY_MAP.keys())}",
                success=False,
            )

        gen_fn, topo_label = entry
        target = (
            Path(output_dir)
            if output_dir
            else (get_config_dir() / "packet_tracer" / clean_name)
        )
        target.mkdir(parents=True, exist_ok=True)

        try:
            config_files = gen_fn(target)
            readme_file = _generate_readme(
                clean_name, topo_label, config_files, target, topo_key
            )
            all_files = config_files + [readme_file]
        except Exception as e:
            return ToolResult(
                tool_name="cisco_packet_tracer",
                content=f"Generation failed: {e}",
                success=False,
            )

        return ToolResult(
            tool_name="cisco_packet_tracer",
            content=f"Generated {topo_label} demo in {target}:\n- "
            + "\n- ".join(all_files),
            success=True,
            metadata={
                "project_name": clean_name,
                "topology": topo_key,
                "target_directory": str(target),
                "files": all_files,
            },
        )


__all__ = ["CiscoPacketTracerTool"]
