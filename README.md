# Redmi AX3000 (RA81) — ImmortalWrt 主线固件

用 **ImmortalWrt master（内核 6.18）** 编译红米 AX3000，而不是厂商 QSDK 分支。

板级支持在独立仓 **[ra81-support](https://github.com/7noemo/ra81-support)**，
本仓只负责：拉源码 → 注入板级支持 → 编译 → 出固件。

---

## 为什么是 master

| 维度 | 结论 |
|------|------|
| 平台成熟度 | master 的 `qualcommax/ipq50xx` 已有 **30 个** IPQ5018 机型，含同 SoC、同 QCA8337 交换芯片的红米 AX5400 |
| 内核 | 6.18，ath11k multipd 支持完整（IPQ5018 + QCN6122 家族） |
| 稳定性风险 | master 是开发分支，会偶发上游补丁真空期；可用 `source_branch=openwrt-25.12` 改走 6.12 稳定分支 |
| 缺的东西 | 只有三样：**设备树、BDF、设备定义**。平台本身不用移植 |

RA81 不需要"从零移植一个 SoC"，只需要补一个机型定义 —— 这是本方案成立的前提。

## 关键取舍：以太网走 stmmac + DSA

master（6.18）把 IPQ5018 的以太网从 `qca-nss-dp` 换成了 **stmmac**，QCA8337
由 **DSA（qca8k）** 驱动：

```
gmac0 --GE PHY--> QCA8337 Phy4
gmac1 --SGMII---> QCA8337 CPU port
lan1/lan2/lan3/wan = DSA ports
```

这带来一个**必须说清楚的限制**：

> **本固件没有 NSS 硬件加速，也无法在原树上加。**
> NSS 需要 `qca-nss-dp` 挂数据面，而 master 已经把它删了
> （`package/kernel/qca-nss-dp` 在 master 上 404，只在 `openwrt-25.12` 存在）。
>
> 对 RA81 这种**全千兆口**的机器，实际损失很小：stmmac + 软件 NAT 已经能跑满
> 千兆线速。NSS 真正的价值在 Wi-Fi offload 和 2.5G/万兆口。
>
> 四条可能的 NSS 路线（master / 25.12 / 5.15+NSS11.4 / qosmio fork）全部查证过，
> 没有一条能交付，证据与推理见
> **[ra81-support/NSS-FEASIBILITY.md](https://github.com/7noemo/ra81-support/blob/main/NSS-FEASIBILITY.md)**。

### 替代方案：软件数据面调优

`99-ra81-tuning` 首次启动时自动做四件事，对千兆口的实际收益比 NSS 更明显：

| 项 | 作用 |
|----|------|
| flow offloading（软件 flowtable） | 已建立连接走快路径，NAT 转发贴近线速 |
| BBR + fq | 高 RTT 链路吞吐提升 |
| RPS/XPS | 软中断分到两个核，避免单核打满 |
| SQM/CAKE（LuCI 可选） | 抑制 bufferbloat —— 影响体验的是延迟不是峰值 |

> flow offload 与 SQM/CAKE 互斥：SQM 需要看到每个包。开 SQM 时 LuCI 会自动关掉
> flow offload。

## 2.4 GHz 与 board_id

2.4G 是 IPQ5018 内置射频，需要匹配板上的 PA 版本：

- **M81（RA81）= 0x24**
- M79（CR880x）= 0x10

搞错就是经典的"2.4G 消失 / 信号极弱"。

主线 ath11k **不从设备树读 `qcom,board_id`**（只读 `qcom,rproc`），它用
`0:art` 里 QMI CALIB 数据自带的 board_id。RA81 出厂已校准，所以本方案
**不修改 ath11k**。随固件下发的 BDF 同时包含 0x10 和 0x24 两个 variant，
因此同一镜像也能给 CR880x 用。

极端情况下某台机器的 art 报错 id，才需要给 ath11k 打 DT override 补丁 ——
QSDK 时代那个 `board_id-ahb-c000000.wifi` 固件骗术在主线不存在。

## 编译

推送即触发；也可以手动跑 `workflow_dispatch`，可切 `master` / `openwrt-25.12`。

本地：

```bash
git clone https://github.com/7noemo/ra81-support.git
git clone https://github.com/immortalwrt/immortalwrt.git -b master openwrt
./ra81-support/scripts/install-into-openwrt.sh openwrt
cp -r files/. openwrt/files/
cd openwrt
./scripts/feeds update -a && ./scripts/feeds install -a
cp ../configs/ra81.config .config && make defconfig
make -j$(nproc)
```

产物：`bin/targets/qualcommax/ipq50xx/*redmi*ax3000*`

## 刷机

要求**原厂分区表**（22 个分区，`rootfs` 在 `0xa80000`，36 MiB）和原厂 U-Boot。

- 固件写入 **slot A**（mtd18 `rootfs`），slot B 保持只读不动
- 想回原厂：小米维修工具 + 刷回 mtd1/mtd11/mtd12，路还在

首次写入用 factory UBI，之后正常 `sysupgrade`。

> **刷机有风险。第一次写之前先做完整 NAND 备份。**

## 首次启动

- 无线默认：CN / 2.4G ch6 HE40 / 5G ch36 HE160（按频段识别，不按 radio 序号）
- 诊断：`ra81-wifi-diag`，贴恩山/提 issue 时请附上它的输出
- LuCI 中文已内置（通过 `CONFIG_LUCI_LANG_zh_Hans`，不是直接列 i18n 包）

## 预置软件

LuCI + 中文、防火墙、TTYD 终端、SQM、WOL、DDNS、UPnP、Argon 主题、
BBR、USB 存储（ext4/exfat）、iperf3、ethtool、tcpdump、htop、curl、sftp-server。

## 许可证

配置与脚本：MIT。设备树与 BDF：见 ra81-support（GPL-2.0-or-later + 厂商校准数据）。
