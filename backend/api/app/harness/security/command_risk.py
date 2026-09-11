"""bash 命令风险分级（提前提示 + 纵深防御，**非安全边界**）。

三档权限用它决定 bash 是否审批/拒绝：disaster（灾难，三档都拒）、
destructive（破坏，三档都审批）、normal（普通，按档位）。

**重要**：文本分级可被同义变体/别名/编码绕过，真正的边界是沙箱容器挂载与
`unshare` 命名空间；本模块只做"破坏发生前的提示与兜底"，禁止当作唯一防线。
解析失败一律按 destructive（保守，宁可多问一次）。
"""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import Literal

Risk = Literal["disaster", "destructive", "normal"]

# 命令名前缀：剥离后取真实命令名（如 sudo rm → rm）。
_PREFIXES = {"sudo", "doas", "env", "nohup", "command", "exec", "time", "nice", "ionice", "setsid"}

# 灾难级命令（三档都拒绝）。
_DISASTER_CMDS = {"mkfs", "wipefs", "shutdown", "reboot", "halt", "poweroff", "fdisk", "parted"}

# 破坏级命令（三档都审批）。
_DESTRUCTIVE_CMDS = {
    "rm", "rmdir", "mv", "chmod", "chown", "chgrp", "dd", "truncate", "shred", "ln",
    "kill", "pkill", "killall", "sudo", "su", "doas", "mount", "umount", "systemctl",
    "service", "crontab", "at", "useradd", "userdel", "usermod", "groupadd", "passwd",
    "visudo", "insmod", "modprobe", "rmmod", "iptables", "nft", "ip", "docker", "kubectl",
    "apt", "apt-get", "dpkg", "yum", "dnf", "apk", "pacman", "snap", "pip", "pip3",
    "npm", "yarn", "pnpm", "gem", "make",
}

# 系统路径（灾难级写入/删除目标）。
_SYSTEM_PATHS = {
    "/", "/etc", "/usr", "/var", "/bin", "/sbin", "/boot", "/dev", "/proc", "/sys",
    "/root", "/lib", "/lib64", "/home",
}
_HOME_ALIASES = {"~", "~/*", "$home", "${home}"}

# `... | sh` 之类的管道执行（拉取即执行）。
_PIPE_TO_SHELL = re.compile(r"\|\s*(?:sudo\s+)?(?:sh|bash|zsh|dash|ksh|python3?|perl|ruby)\b")
# fork 炸弹经典形态（去掉空白后匹配）。
_FORK_BOMB = re.compile(r":\(\)\s*\{|\(\)\s*\{.*:\s*\|")


def _is_system_target(token: str) -> bool:
    """判断删除/写入目标是否落在系统路径（含 ``/`` 与 ``~``）。"""
    t = token.strip().strip("'\"")
    if t in _HOME_ALIASES or t in {"/*", "/.", "/.."}:
        return True
    if not t.startswith("/"):
        return False
    # 待执行的是 Linux 沙箱中的 bash；宿主即使是 Windows 也必须按 POSIX 路径归一。
    normalized = posixpath.normpath(t)
    return normalized in _SYSTEM_PATHS


def _strip_prefixes(tokens: list[str]) -> list[str]:
    """剥离 env 赋值与命令前缀，返回从真实命令名开始的切片。"""
    idx = 0
    while idx < len(tokens) and "=" in tokens[idx] and not tokens[idx].startswith("-"):
        idx += 1
    while idx < len(tokens) and posixpath.basename(tokens[idx]) in _PREFIXES:
        idx += 1
    return tokens[idx:]


def _classify_segment(segment: str) -> Risk:
    """对单个命令段（已按 ; && || | 换行切分）做分级。"""
    seg = segment.strip()
    if not seg:
        return "normal"
    if _FORK_BOMB.search(seg.replace(" ", "")):
        return "disaster"
    try:
        tokens = shlex.split(seg)
    except ValueError:
        return "destructive"  # 解析失败保守处理
    if not tokens:
        return "normal"
    real = _strip_prefixes(tokens)
    if not real:
        return "normal"
    cmd = posixpath.basename(real[0])
    rest = real[1:]
    # 灾难：整盘/系统目录递归删除、块设备写、系统目录写入
    if cmd.startswith("mkfs") or cmd in _DISASTER_CMDS:
        return "disaster"
    if cmd == "rm" and any(_is_system_target(a) for a in rest if not a.startswith("-")):
        return "disaster"
    if cmd == "dd" and any("of=/dev/" in a or "of=/proc/" in a or "of=/sys/" in a for a in rest):
        return "disaster"
    if cmd in {"chmod", "chown", "chgrp"} and any(_is_system_target(a) for a in rest):
        return "disaster"
    # 破坏：命令名命中破坏集合
    if cmd in _DESTRUCTIVE_CMDS:
        return "destructive"
    return "normal"


def _split_segments(command: str) -> list[str]:
    """按未转义的 ; && || | & 与换行切分（quote-aware）。"""
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == '"':
                i += 1
                if i < n:
                    buf.append(command[i])
            elif c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\\":
            i += 1
            if i < n:
                buf.append(command[i])
            i += 1
            continue
        if c in ";|&\n":
            segments.append("".join(buf))
            buf = []
            if c in "|&" and i + 1 < n and command[i + 1] == c:
                i += 2
            else:
                i += 1
            continue
        buf.append(c)
        i += 1
    segments.append("".join(buf))
    return [seg.strip() for seg in segments if seg.strip()]


def _substitutions(command: str) -> list[str]:
    """提取 ``$(...)`` 与反引号内的子命令，供递归分级。"""
    subs: list[str] = []
    i, n = 0, len(command)
    while i < n:
        if command[i] == "$" and i + 1 < n and command[i + 1] == "(":
            depth, j, start = 1, i + 2, i + 2
            while j < n and depth:
                if command[j] == "(":
                    depth += 1
                elif command[j] == ")":
                    depth -= 1
                j += 1
            subs.append(command[start : j - 1])
            i = j
        elif command[i] == "`":
            j = command.find("`", i + 1)
            if j == -1:
                break
            subs.append(command[i + 1 : j])
            i = j + 1
        else:
            i += 1
    return subs


def classify(command: str) -> Risk:
    """对完整命令分级：任一子段/子命令为 disaster/destructive 即整体提升。"""
    text = str(command or "").strip()
    if not text:
        return "normal"
    results = [_classify_segment(seg) for seg in _split_segments(text)]
    results.extend(classify(sub) for sub in _substitutions(text))
    if _PIPE_TO_SHELL.search(text):
        results.append("destructive")
    if "disaster" in results:
        return "disaster"
    if "destructive" in results:
        return "destructive"
    return "normal"
