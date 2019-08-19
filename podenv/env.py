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

from __future__ import annotations
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from pathlib import Path
from textwrap import dedent
from typing import Callable, Dict, List, Optional, Set, Tuple, Union
try:
    import selinux  # type: ignore
    HAS_SELINUX = True
except ImportError:
    HAS_SELINUX = False


ExecArgs = List[str]
Requirements = List[str]
Info = Dict[str, Union[str, Requirements]]
Overlay = Union[str, Dict[str, str]]
UserNotif = Callable[[str], None]
Task = Dict[str, Union[str, Dict[str, str]]]
StrOrList = Union[str, List[str]]


def asList(param: StrOrList = []) -> StrOrList:
    if isinstance(param, list):
        return param
    return param.split()


class Runtime(ABC):
    @abstractmethod
    def exists(self, autoUpdate: bool) -> bool:
        ...

    @abstractmethod
    def loadInfo(self) -> None:
        ...

    @abstractmethod
    def getCustomizations(self) -> List[str]:
        ...

    @abstractmethod
    def getInstalledPackages(self) -> List[str]:
        ...

    @abstractmethod
    def getSystemMounts(self) -> ExecArgs:
        ...

    @abstractmethod
    def needUpdate(self) -> bool:
        ...

    @abstractmethod
    def getExecName(self) -> ExecArgs:
        ...

    @abstractmethod
    def create(self) -> None:
        ...

    @abstractmethod
    def update(self) -> None:
        ...

    @abstractmethod
    def install(self, packages: Set[str]) -> None:
        ...

    @abstractmethod
    def customize(self, commands: List[Tuple[str, str]]) -> None:
        ...


@dataclass
class ExecContext:
    """The intermediary podman context representation"""
    environ: Dict[str, str] = field(default_factory=dict)
    mounts: Dict[Path, Path] = field(default_factory=dict)
    syscaps: List[str] = field(default_factory=list)
    execArgs: ExecArgs = field(default_factory=list)
    home: Path = field(default_factory=Path)
    cwd: Path = field(default_factory=Path)
    xdgDir: Path = field(default_factory=Path)
    seLinuxLabel: str = ""
    seccomp: str = ""
    networkNamespace: str = ""

    def args(self, *args: str) -> None:
        self.execArgs.extend(args)

    def hasNetwork(self) -> bool:
        return not self.networkNamespace or self.networkNamespace != "none"

    def hasDirectNetwork(self) -> bool:
        return not self.networkNamespace or self.networkNamespace == "host"

    def getArgs(self) -> ExecArgs:
        args = []

        if self.seLinuxLabel:
            args.extend(["--security-opt", f"label={self.seLinuxLabel}"])
        if self.seccomp:
            args.extend(["--security-opt", f"seccomp={self.seccomp}"])

        if self.networkNamespace:
            args.extend(["--network", self.networkNamespace])

        if self.cwd == Path():
            self.cwd = self.home
        args.extend(["--workdir", str(self.cwd)])

        for mount in sorted(self.mounts.keys()):
            args.extend(["-v", "{hostPath}:{containerPath}".format(
                hostPath=self.mounts[mount].expanduser().resolve(),
                containerPath=mount)])

        for cap in set(self.syscaps):
            args.extend(["--cap-add", cap])

        for e, v in sorted(self.environ.items()):
            args.extend(["-e", "%s=%s" % (e, v)])

        return args + self.execArgs


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

        return dedent(f"""            # Generated by podenv
            [Desktop Entry]
            Type=Application
            Name={self.name}
            Comment=Podenv launcher for {self.envName}
            Exec=podenv {self.envName}
            Terminal={terminal}
            {icon}
        """)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"podenv - {self.envName}"


@dataclass
class Env:
    """The user provided container representation"""
    name: str = field(default="", metadata=dict(
        doc="The name of the environment"))
    description: Optional[str] = field(default="", metadata=dict(
        doc="Environment description"))
    parent: str = field(default="", metadata=dict(
        doc="A parent environment name to inherit attributes from."))
    desktop: Optional[DesktopEntry] = field(default=None, metadata=dict(
        doc="A desktop launcher entry file definition"))
    image: str = field(default="", metadata=dict(
        doc="The container image reference"))
    rootfs: str = field(default="", metadata=dict(
        doc="The path of a rootfs"))
    dns: str = field(default="", metadata=dict(
        doc="A custom DNS server"))
    imageCustomizations: List[str] = field(default_factory=list, metadata=dict(
        doc="List of shell commands to execute and commit in the image"))
    imageTasks: List[Task] = field(default_factory=list, metadata=dict(
        doc="List of ansible like command to commit to the image"))
    packages: List[str] = field(default_factory=list, metadata=dict(
        doc="List of packages to be installed in the image"))
    command: ExecArgs = field(default_factory=list, metadata=dict(
        doc="Container starting command"))
    args: ExecArgs = field(default_factory=list, metadata=dict(
        doc="Optional arguments to append to the command"))
    environ: Dict[str, str] = field(default_factory=dict, metadata=dict(
        doc="User environ(7)"))
    syscaps: List[str] = field(default_factory=list, metadata=dict(
        doc="List of system capabilities(7)"))
    mounts: Dict[str, str] = field(default_factory=dict, metadata=dict(
        doc="Extra mountpoints"))
    capabilities: Dict[str, bool] = field(default_factory=dict, metadata=dict(
        doc="List of capabilities"))
    network: str = field(default="", metadata=dict(
        doc="Name of a network to be shared by multiple environment"))
    requires: StrOrList = field(default_factory=asList, metadata=dict(
        doc="List of required environments"))
    overlays: List[Overlay] = field(default_factory=list, metadata=dict(
        doc="List of overlay to copy in runtime directory"))
    home: str = field(default="", metadata=dict(
        doc="Container home path mount"))
    shmsize: str = field(default="", metadata=dict(
        doc="The shm-size value string"))
    ports: List[str] = field(default_factory=list, metadata=dict(
        doc="List of port to expose on the host"))

    # Internal attribute
    runtime: Optional[Runtime] = field(default=None, metadata=dict(
        internal=True))
    ctx: ExecContext = field(default_factory=ExecContext, metadata=dict(
        internal=True))
    runDir: Optional[Path] = field(default=None, metadata=dict(
        internal=True))
    overlaysDir: Optional[Path] = field(default=None, metadata=dict(
        internal=True))
    manageImage: bool = field(default=True, metadata=dict(
        internal=True))
    autoUpdate: bool = field(default=False, metadata=dict(
        internal=True))
    mountCache: bool = field(default=False, metadata=dict(
        internal=True))
    configFile: Optional[Path] = field(default=None, metadata=dict(
        internal=True))

    def applyParent(self, parentEnv: Env) -> None:
        for attr in fields(Env):
            if attr.name in ('name', 'parent'):
                continue
            attrValue = getattr(parentEnv, attr.name)
            if getattr(self, attr.name) in (None, "", [], {}):
                setattr(self, attr.name, attrValue)
            elif isinstance(attrValue, list):
                if attr.name == "command":
                    continue
                # List are extended
                setattr(self, attr.name, getattr(self, attr.name) +
                        getattr(parentEnv, attr.name))
            elif isinstance(attrValue, dict):
                # Dictionary are updated in reverse
                mergedDict = getattr(parentEnv, attr.name)
                mergedDict.update(getattr(self, attr.name))
                setattr(self, attr.name, mergedDict)

    def __post_init__(self) -> None:
        if not self.configFile:
            raise RuntimeError("No configFile context")
        if self.desktop:
            # Ignoring type here just to convert yaml dict to DesktopEntry
            self.desktop = DesktopEntry(  # type: ignore
                envName=self.name,
                terminal=self.capabilities.get("terminal", False),
                relPath=self.configFile.parent,
                **self.desktop)
        # Support retro cap name written in camelCase
        retroCap = {}
        for cap, value in self.capabilities.items():
            if cap in ("mountCwd", "mountRun", "autoUpdate"):
                cap = re.sub('([CRU])', r'-\1', cap).lower()
                retroCap[cap] = value

            if cap not in ValidCap:
                raise RuntimeError(f"{self.name}: unknown cap {cap}")
        self.capabilities.update(retroCap)
        # Convert str to list
        self.requires = asList(self.requires)


def rootCap(active: bool, ctx: ExecContext, _: Env) -> None:
    "run as root"
    if active:
        ctx.home = Path("/root")
        ctx.xdgDir = Path("/run/user/0")
    else:
        ctx.home = Path("/home/user")
        ctx.xdgDir = Path("/run/user/1000")
        ctx.args("--user", "1000")
    ctx.environ["XDG_RUNTIME_DIR"] = str(ctx.xdgDir)
    ctx.environ["HOME"] = str(ctx.home)


def getUidMap(_: Env) -> ExecArgs:
    return ["--uidmap", "1000:0:1", "--uidmap", "0:1:999",
            "--uidmap", "1001:1001:%s" % (2**16 - 1001)]


def uidmapCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "map host uid"
    if active:
        ctx.execArgs.extend(getUidMap(env))


def privilegedCap(active: bool, ctx: ExecContext, _: Env) -> None:
    "run as privileged container"
    if active:
        ctx.args("--privileged")


def terminalCap(active: bool, ctx: ExecContext, _: Env) -> None:
    "interactive mode"
    if active:
        ctx.args("-it")
        ctx.args("--detach-keys", "ctrl-e,e")


def networkCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "enable network"
    if env.network:
        ctx.networkNamespace = f"container:net-{env.network}"

    if not active and not env.network:
        ctx.networkNamespace = "none"


def manageImageCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "manage the image with buildah"
    env.manageImage = active


def mountCwdCap(active: bool, ctx: ExecContext, _: Env) -> None:
    "mount cwd to /data"
    if active:
        ctx.cwd = Path("/data")
        ctx.mounts[ctx.cwd] = Path()


def mountRunCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "mount home and tmp to host tmpfs"
    if active:
        if env.runDir is None:
            raise RuntimeError("runDir isn't set")
        if not ctx.mounts.get(ctx.home) and not env.home:
            ctx.mounts[ctx.home] = env.runDir / "home"
        if not ctx.mounts.get(Path("/tmp")):
            ctx.mounts[Path("/tmp")] = env.runDir / "tmp"


def mountCacheCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "mount image build cache"
    if active:
        env.mountCache = True


def ipcCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share host ipc"
    if active:
        ctx.args("--ipc=host")


def x11Cap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share x11 socket"
    if active:
        ctx.mounts[Path("/tmp/.X11-unix")] = Path("/tmp/.X11-unix")
        ctx.environ["DISPLAY"] = os.environ["DISPLAY"]


def pulseaudioCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share pulseaudio socket"
    if active:
        ctx.mounts[Path("/etc/machine-id:ro")] = Path("/etc/machine-id")
        ctx.mounts[ctx.xdgDir / "pulse"] = \
            Path(os.environ["XDG_RUNTIME_DIR"]) / "pulse"
        # Force PULSE_SERVER environment so that when there are more than
        # one running, pulse client aren't confused by different uid
        ctx.environ["PULSE_SERVER"] = str(ctx.xdgDir / "pulse" / "native")


def gitCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share .gitconfig and excludesfile"
    if active:
        gitconfigFile = Path("~/.gitconfig").expanduser().resolve()
        if gitconfigFile.is_file():
            ctx.mounts[ctx.home / ".gitconfig"] = gitconfigFile
            for line in gitconfigFile.read_text().split('\n'):
                line = line.strip()
                if line.startswith("excludesfile"):
                    excludeFileName = line.split('=')[1].strip()
                    excludeFile = Path(
                        excludeFileName).expanduser().resolve()
                    if excludeFile.is_file():
                        ctx.mounts[ctx.home / excludeFileName.replace(
                            '~/', '')] = excludeFile
                # TODO: improve git crential file discovery
                elif "store --file" in line:
                    storeFileName = line.split()[-1]
                    storeFile = Path(storeFileName).expanduser().resolve()
                    if storeFile.is_file():
                        ctx.mounts[ctx.home / storeFileName.replace(
                            '~/', '')] = storeFile


def editorCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "setup editor env"
    if active:
        ctx.environ["EDITOR"] = os.environ.get("EDITOR", "vi")
        # TODO: manage package name translation based on system type.
        env.packages.append("vi")


def sshCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share ssh agent and keys"
    if active:
        ctx.environ["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
        sshSockPath = Path(os.environ["SSH_AUTH_SOCK"])
        ctx.mounts[Path(sshSockPath)] = sshSockPath
        ctx.mounts[ctx.home / ".ssh"] = Path("~/.ssh")


def gpgCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share gpg agent"
    if active:
        gpgSockDir = Path(os.environ["XDG_RUNTIME_DIR"]) / "gnupg"
        ctx.mounts[ctx.xdgDir / "gnupg"] = gpgSockDir
        ctx.mounts[ctx.home / ".gnupg"] = Path("~/.gnupg")


def webcamCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share webcam device"
    if active:
        for device in list(filter(lambda x: x.startswith("video"),
                                  os.listdir("/dev"))):
            ctx.args("--device", str(Path("/dev") / device))


def driCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share graphic device"
    if active:
        ctx.args("--device", "/dev/dri")


def kvmCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share kvm device"
    if active:
        ctx.args("--device", "/dev/kvm")


def tunCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "share tun device"
    if active:
        ctx.args("--device", "/dev/net/tun")


def selinuxCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "enable SELinux"
    if not active:
        ctx.seLinuxLabel = "disable"


def seccompCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "enable seccomp"
    if not active:
        ctx.seccomp = "unconfined"


def ptraceCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "enable ptrace"
    if active:
        ctx.syscaps.append("SYS_PTRACE")


def setuidCap(active: bool, ctx: ExecContext, env: Env) -> None:
    "enable setuid"
    if active:
        for cap in ("SETUID", "SETGID"):
            ctx.syscaps.append(cap)


def autoUpdateCap(active: bool, _: ExecContext, env: Env) -> None:
    "keep environment updated"
    if active:
        env.autoUpdate = True


def camelCaseToHyphen(name: str) -> str:
    return re.sub('([A-Z]+)', r'-\1', name).lower()


Capability = Callable[[bool, ExecContext, Env], None]
Capabilities: List[Tuple[str, Optional[str], Capability]] = [
    (camelCaseToHyphen(func.__name__[:-3]), func.__doc__, func) for func in [
        manageImageCap,
        rootCap,
        privilegedCap,
        terminalCap,
        ipcCap,
        x11Cap,
        pulseaudioCap,
        gitCap,
        editorCap,
        sshCap,
        gpgCap,
        webcamCap,
        driCap,
        kvmCap,
        tunCap,
        seccompCap,
        selinuxCap,
        setuidCap,
        ptraceCap,
        networkCap,
        mountCwdCap,
        mountRunCap,
        mountCacheCap,
        autoUpdateCap,
        uidmapCap,
    ]]
ValidCap: Set[str] = set([cap[0] for cap in Capabilities])


def validateEnv(env: Env) -> None:
    """Sanity check and warn user about missing setting"""
    def warn(msg: str) -> None:
        print(f"\033[93m{msg}\033[m")

    # Check if SELinux will block socket access
    if env.capabilities.get("selinux"):
        for cap in ("x11", "tun", "pulseaudio"):
            if env.capabilities.get(cap):
                warn(
                    f"SELinux is disabled because capability '{cap}' need "
                    "extra type enforcement that are not currently supported.")
                selinuxCap(False, env.ctx, env)
                env.capabilities["selinux"] = False

    # Check for uid permissions
    if not env.capabilities.get("root") and not env.capabilities.get("uidmap"):
        for cap in ("x11", "pulseaudio", "ssh", "gpg"):
            if env.capabilities.get(cap):
                warn(
                    f"UIDMap is required because '{cap}' need "
                    "DAC access to the host file")
                uidmapCap(True, env.ctx, env)
                break

    # Check for system capabilities
    if env.capabilities.get("tun") and "NET_ADMIN" not in env.ctx.syscaps:
        warn(f"NET_ADMIN capability is needed by the tun device")
        env.ctx.syscaps.append("NET_ADMIN")

    # Check mount points labels
    if env.capabilities.get("selinux") and HAS_SELINUX:
        label = "container_file_t"
        for hostPath in env.ctx.mounts.values():
            hostPath = hostPath.expanduser().resolve()
            if hostPath.exists() and \
               selinux.getfilecon(str(hostPath))[1].split(':')[2] != label:
                warn(f"SELinux is disabled because {hostPath} doesn't have "
                     f"the {label} label. To set the label run: "
                     f"chcon -Rt {label} {hostPath}")
                selinuxCap(False, env.ctx, env)

    # Check mount points permissions
    for hostPath in env.ctx.mounts.values():
        hostPath = hostPath.expanduser().resolve()
        if hostPath.exists() and not os.access(str(hostPath), os.R_OK):
            warn(f"{hostPath} is not readable by the current user.")

    # Check for home mount point
    if env.overlays and not env.ctx.mounts.get(env.ctx.home):
        warn(f"overlay needs a home mount point, "
             "mountRun capability is enabled.")
        mountRunCap(True, env.ctx, env)

    # Check for image management
    if not env.manageImage:
        if env.packages:
            warn("manage-image capability is required for packages")
            manageImageCap(True, env.ctx, env)
        if env.imageCustomizations or env.imageTasks:
            warn("manage-image capability is required for image tasks")
            manageImageCap(True, env.ctx, env)


def prepareEnv(env: Env, cliArgs: List[str]) -> Tuple[str, ExecArgs, ExecArgs]:
    """Generate podman exec args based on capabilities"""
    # Apply capabilities
    for name, _, capability in Capabilities:
        capability(env.capabilities.get(name, False), env.ctx, env)

    # Apply extra settings from the environment definition:
    args = ["--hostname", env.name]
    if env.dns and env.ctx.hasDirectNetwork():
        args.append(f"--dns={env.dns}")
    if env.shmsize:
        args.append(f"--shm-size={env.shmsize}")
    if env.home:
        env.ctx.mounts[env.ctx.home] = Path(env.home).expanduser().resolve()
    if env.ports:
        for port in env.ports:
            port = port.format(**env.environ)
            args.append(f"--publish={port}")

    env.ctx.syscaps.extend(env.syscaps)
    env.ctx.environ.update(env.environ)

    for containerPath, hostPathStr in env.mounts.items():
        hostPath = Path(hostPathStr).expanduser().resolve()
        if containerPath.startswith("~/"):
            env.ctx.mounts[env.ctx.home / containerPath[2:]] = hostPath
        else:
            env.ctx.mounts[Path(containerPath)] = hostPath

    # Look for file argument requirement
    fileArg: Optional[Path] = None
    if "$1" in env.command:
        if len(cliArgs) > 1:
            raise RuntimeError("Multiple file input %s" % cliArgs)
        if cliArgs:
            fileArg = Path(cliArgs.pop()).expanduser().resolve(strict=True)
            env.ctx.mounts[Path("/tmp") / fileArg.name] = fileArg

    commandArgs: List[str] = []
    for command in env.command:
        if command == "$@" and cliArgs:
            commandArgs += cliArgs
        elif command == "$1" and fileArg:
            commandArgs.append("/tmp/" + fileArg.name)
        else:
            commandArgs.append(command)

    # Only use cli args when env isn't a shell
    if not commandArgs or commandArgs[-1] != "/bin/bash":
        for arg in env.args + cliArgs:
            commandArgs.append(arg)

    # Sanity checks
    validateEnv(env)

    # OCI doesn't let you join a netns without the userns when using uidmap...
    if env.capabilities.get("uidmap") and env.ctx.networkNamespace.startswith(
            "container:"):
        env.ctx.args("--userns", env.ctx.networkNamespace)

    return env.name, args + env.ctx.getArgs(), list(map(str, commandArgs))


def cleanupEnv(env: Env) -> None:
    ...
