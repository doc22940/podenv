# Copyright 2019 Red Hat
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
This module defines types
"""

from __future__ import annotations
import copy
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Callable, Dict, List, Optional, Union


@dataclass
class User:
    """Container user information"""
    name: str
    home: Path
    uid: int


@dataclass
class Volume:
    """A volume information"""
    name: str
    readOnly: bool = False


@dataclass
class BuildContext:
    """Minimal execution context to be used for image building"""
    mounts: Optional[Dict[HostPath, ContainerPath]] = None


@dataclass
class DesktopEntry:
    """A desktop file definition"""
    envName: str
    relPath: Path
    terminal: bool
    name: str = field(default="")
    icon: str = field(default="")

    def format(self) -> str:
        if self.icon:
            if (self.relPath / self.icon).exists():
                iconPath = (self.relPath / self.icon).expanduser().resolve()
            elif Path(self.icon).exists():
                iconPath = Path(self.icon).expanduser().resolve()
            else:
                iconPath = Path(self.icon)
            icon = f"Icon={iconPath}"
        else:
            icon = ""
        terminal = "true" if self.terminal else "false"

        return dedent(f"""
            # Generated by podenv
            [Desktop Entry]
            Type=Application
            Name={self.name}
            Comment=Podenv launcher for {self.envName}
            Exec=podenv {self.envName}
            Terminal={terminal}
            {icon}
        """[1:])

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"podenv - {self.envName}"


@dataclass
class ExecContext:
    """The intermediary execution context representation"""
    name: str
    imageName: str
    volumes: Optional[Volumes]
    desktop: Optional[DesktopEntry]
    commandArgs: List[str]
    imageBuildCtx: Optional[BuildContext] = None
    containerFile: Optional[str] = None
    containerUpdate: Optional[str] = None

    # Following collections are optionals and set to empty value by default
    environ: Dict[str, str] = field(default_factory=dict)
    mounts: Dict[Path, Union[Path, Volume]] = field(default_factory=dict)
    syscaps: List[str] = field(default_factory=list)
    sysctls: List[str] = field(default_factory=list)
    devices: List[Path] = field(default_factory=list)
    addHosts: Dict[str, str] = field(default_factory=dict)
    hostPreTasks: List[str] = field(default_factory=list)
    hostPostTasks: List[str] = field(default_factory=list)
    podmanArgs: List[str] = field(default_factory=list)

    # home and xdgDir are always set by the root cap function
    home: Optional[Path] = None
    xdgDir: Path = field(default_factory=Path)

    cwd: Optional[Path] = None
    runDir: Optional[Path] = None
    detachKeys: Optional[str] = None
    seLinuxLabel: Optional[str] = None
    seccomp: Optional[str] = None
    shmsize: Optional[str] = None
    namespaces: Dict[str, str] = field(default_factory=dict)
    network: Optional[str] = None

    dns: Optional[str] = None
    hostname: Optional[str] = None
    user: Optional[User] = None

    # Set by caps
    interactive: bool = False
    username: Optional[str] = None
    privileged: bool = False
    uidmaps: bool = False

    def getUidMaps(self) -> ExecArgs:
        return ["--uidmap", "1000:0:1", "--uidmap", "0:1:1000",
                "--uidmap", "1001:1001:%s" % (2**16 - 1001)]

    def hasNetwork(self) -> bool:
        return not self.namespaces.get("network") or \
            self.namespaces["network"] != "none"

    def hasDirectNetwork(self) -> bool:
        return not self.namespaces.get("network") or \
            self.namespaces["network"] == "host"

    def getHosts(self) -> ExecArgs:
        args = []
        for hostName, hostIp in self.addHosts.items():
            args.extend(["--add-host", f"{hostName}:{hostIp}"])
        return args

    def getArgs(self) -> ExecArgs:
        args = copy.copy(self.podmanArgs)

        if self.hostname:
            args.extend(["--hostname", self.hostname])

        if self.seLinuxLabel:
            args.extend(["--security-opt", f"label={self.seLinuxLabel}"])
        if self.seccomp:
            args.extend(["--security-opt", f"seccomp={self.seccomp}"])

        for ns, val in self.namespaces.items():
            args.extend([f"--{ns}", val])

        if self.hasDirectNetwork():
            args.extend(self.getHosts())

        if self.cwd:
            args.extend(["--workdir", str(self.cwd)])

        if self.dns and self.hasDirectNetwork():
            args.append(f"--dns={self.dns}")

        for mount in sorted(self.mounts.keys()):
            hostMount = self.mounts[mount]
            if isinstance(hostMount, Path):
                hostPath = str(hostMount.expanduser().resolve())
            else:
                hostPath = f"{hostMount.name}"
            args.extend(["-v", "{hostPath}:{containerPath}".format(
                hostPath=hostPath,
                containerPath=mount)])

        for device in set(self.devices):
            args.extend(["--device", str(device)])

        for cap in set(self.syscaps):
            args.extend(["--cap-add", cap])

        for ctl in set(self.sysctls):
            args.extend(["--sysctl", ctl])

        for e, v in sorted(self.environ.items()):
            args.extend(["-e", "%s=%s" % (e, v)])

        if self.username:
            args.extend(["--user", self.username])

        if self.uidmaps:
            args.extend(self.getUidMaps())

        if self.privileged:
            args.extend(["--privileged"])

        if self.detachKeys is not None:
            args.extend(["--detach-keys", self.detachKeys])

        if self.interactive:
            args.extend(["-it"])

        if self.shmsize:
            args.extend([f"--shm-size={self.shmsize}"])

        return args


HostPath = Path
ContainerPath = Path
Mounts = Dict[ContainerPath, HostPath]
Volumes = Dict[ContainerPath, Volume]
ExecArgs = List[str]
UserNotif = Callable[[str], None]
Task = Dict[str, Union[str, Dict[str, str]]]
Capability = Callable[[bool, ExecContext], None]
