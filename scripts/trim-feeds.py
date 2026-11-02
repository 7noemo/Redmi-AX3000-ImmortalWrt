#!/usr/bin/env python3
"""
按 36 MiB 的 rootfs 槽位修剪第三方 feed —— 只动两处，全部带校验。

用法:  scripts/trim-feeds.py /path/to/openwrt

1. feeds/*/net/v2ray-geodata/Makefile
   v2fly 的 geoip.dat 装完 22 MiB，36 MiB 的槽位塞不进去。换成 MetaCubeX
   的 geoip-lite.dat（0.2 MiB，只含 CN + 私有网段，正好是「国内直连」要用
   的那个集合）。geosite 不动。

2. feeds/passwall2/luci-app-passwall2/Makefile
   把 +geoview 从 LUCI_DEPENDS 里摘掉。geoview 是 Go 写的 GeoIP 解析器
   （装完 ~5 MiB），运行时是可选的：
       nftables.sh: [ -z "$(first_type geoview)" ] && enable_geoview_ip=0
   缺了它只是不能按 GeoIP 拆分分流，代理本身照常工作。

两个改写都用「结构定位 + 断言」，上游改版本号/改上下文也不会让 patch 失效，
但一旦结构对不上会立刻报错退出，而不是静默产出超尺寸镜像。
"""

import re
import sys
import pathlib

fail = []


def find_pkg(root: pathlib.Path, name: str):
    """在 feeds/* 下找包目录（feeds/<feed>/<subpath>/<name>）。"""
    hits = [p for p in (root / "feeds").glob(f"*/**/{name}") if p.is_dir()]
    return hits


def patch_geoip(root: pathlib.Path) -> None:
    hits = find_pkg(root, "v2ray-geodata")
    if not hits:
        fail.append("v2ray-geodata 不在任何 feed 里（feeds 没更新？）")
        return

    mk = hits[0] / "Makefile"
    s = mk.read_text()

    if "geoip-lite.dat" in s:
        print(f"  SKIP {mk.relative_to(root)} 已经是 geoip-lite")
        return

    new = """# --- RA81 36 MiB 槽位适配（由 scripts/trim-feeds.py 改写）-----------------
# v2fly 的 geoip.dat 装完是 22 MiB，和内核 + squashfs 一起塞不进 36 MiB 的
# rootfs 槽位。换成 MetaCubeX 的 geoip-lite.dat：只含 CN + 私有网段，正好是
# 「国内直连」需要的那个集合，0.2 MiB。
# 上游只发滚动 tag "latest"，内容随时变，所以 HASH:=skip（download.pl 认这个值）。
# 版本号用日期占位，保证 opkg/apk 的 version 语法合法。
GEOIP_VER:=20260101
GEOIP_FILE:=geoip-lite.dat
define Download/geoip
  URL:=https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/
  URL_FILE:=geoip-lite.dat
  FILE:=$(GEOIP_FILE)
  HASH:=skip
endef

"""

    # 从 GEOIP_VER:= 到 GEOSITE_VER:= 之间就是 geoip 的下载定义
    pat = re.compile(r"^GEOIP_VER:=.*?(?=^GEOSITE_VER:=)", re.S | re.M)
    if not pat.search(s):
        fail.append(f"{mk}: 找不到 GEOIP_VER / GEOSITE_VER 下载块，结构变了")
        return

    s2 = pat.sub(new, s, count=1)
    mk.write_text(s2)
    print(f"  OK   {mk.relative_to(root)}: geoip.dat -> geoip-lite.dat (HASH:=skip)")


def patch_geoview(root: pathlib.Path) -> None:
    hits = find_pkg(root, "luci-app-passwall2")
    if not hits:
        fail.append("luci-app-passwall2 不在任何 feed 里（passwall2 feed 没装？）")
        return

    mk = hits[0] / "Makefile"
    s = mk.read_text()

    idx = s.find("LUCI_DEPENDS:=")
    if idx < 0:
        fail.append(f"{mk}: 没有 LUCI_DEPENDS")
        return

    # LUCI_DEPENDS 是用反斜杠续行的多行赋值，找到最后一行
    end = idx
    while True:
        nl = s.find("\n", end)
        if nl < 0:
            end = len(s)
            break
        if s[:nl].rstrip().endswith("\\"):
            end = nl + 1
        else:
            end = nl
            break

    dep = s[idx:end]
    if "+geoview" not in dep:
        print(f"  SKIP {mk.relative_to(root)} 已经不含 +geoview")
        return

    dep2 = re.sub(r"[ \t]*\+geoview(?=[ \t\n])", "", dep)
    # 摘掉一个 token 后可能留下 "\ " 这种「反斜杠后面还有空格」的行尾，
    # make 会把它当成续行继续吃下一行，必须清掉行尾空白。
    dep2 = "\n".join(line.rstrip() for line in dep2.split("\n"))
    if "+geoview" in dep2:
        fail.append(f"{mk}: +geoview 摘不掉，LUCI_DEPENDS 结构变了")
        return
    if re.search(r"\\ +\S", dep2):
        fail.append(f"{mk}: LUCI_DEPENDS 行尾续行符被破坏，需要人工检查")
        return

    mk.write_text(s[:idx] + dep2 + s[end:])
    print(f"  OK   {mk.relative_to(root)}: 去掉 +geoview 硬依赖")


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not (root / "feeds").is_dir():
        print(f"FATAL: {root} 下没有 feeds/", file=sys.stderr)
        return 1

    print(">>> trim feeds for the 36 MiB rootfs slot")
    patch_geoip(root)
    patch_geoview(root)

    if fail:
        for f in fail:
            print(f"FATAL: {f}", file=sys.stderr)
        return 1
    print(">>> done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
