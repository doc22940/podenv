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
This module interfaces with dhall-lang
"""

import json
from pathlib import Path
from subprocess import Popen, PIPE
from typing import Any, Union

DEFAULT_PATH = Path("~/.local/bin/dhall-to-json").expanduser()
DEFAULT_URL = "https://github.com/dhall-lang/dhall-haskell/releases/download/"\
    "1.27.0/dhall-json-1.5.0-x86_64-linux.tar.bz2"
DEFAULT_HASH = \
    "f8d6e06cd8e731ba3b1d4c67ee5aead76e0a54658a292b78071c9441b565cc2a"


def _install() -> None:
    # TODO: implement opt-out
    import urllib.request
    from hashlib import sha256

    req = urllib.request.urlopen(DEFAULT_URL)
    data = req.read()
    digest = sha256(data).hexdigest()
    if digest != DEFAULT_HASH:
        raise RuntimeError(
            f"{DEFAULT_URL}: expected '{DEFAULT_HASH}' got '{digest}")
    DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    p = Popen(["tar", "-xjf", "-", "--strip-components=2",
               "-C", str(DEFAULT_PATH.parent)],
              stdin=PIPE)
    p.communicate(data)
    if p.wait():
        raise RuntimeError(f"{DEFAULT_URL}: couldn't extract")


def _load(input: Union[Path, str]) -> Any:
    path = str(DEFAULT_PATH if DEFAULT_PATH.exists() else "dhall-to-json")
    if isinstance(input, str):
        proc = Popen([path], stdin=PIPE, stdout=PIPE, stderr=PIPE)
        proc.stdin.write(input.encode('utf-8'))
    else:
        proc = Popen([path, "--file", input], stdout=PIPE, stderr=PIPE)
    stdout, stderr = proc.communicate()
    if stderr:
        raise RuntimeError(f"Dhall error:" + stderr.decode('utf-8'))
    return json.loads(stdout.decode('utf-8'))


def load(input: Union[Path, str]) -> Any:
    try:
        return _load(input)
    except FileNotFoundError:
        _install()
        return _load(input)


if __name__ == "__main__":
    print(load('let x = "Hello dhall" in x'))
