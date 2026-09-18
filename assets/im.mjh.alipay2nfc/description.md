# Alipay2NFC

把支付宝「碰一碰」的 NFC 唤起重定向到你的第二个支付宝（多开客户端）。

贴商户的碰一碰贴纸时，iOS 永远只唤起官方支付宝 —— 因为只有它通过了 `render.alipay.com` 的 AASA 校验，多开包的 bundle id 不在列表里。本插件在官方支付宝收到 URL 的那一刻把它转交给你的多开客户端。

## 效果

```
贴碰一碰贴纸 → 官方支付宝收到 URL → 本插件拦截 → 拉起「支付宝2」进入碰一碰付款页
```

## 特点

- **不需要改 Info.plist，不需要重新签名多开包**
- **不需要任何前置操作**，装完即用
- 多开包的 bundle id 运行时自动发现，任意多开工具都适用
- 纯 `libobjc` 实现，无 CydiaSubstrate 依赖，无配置文件
- 开源地址：https://github.com/5hux1n/Alipay2NFC

## 已知限制

冷启动贴纸时官方支付宝会先闪一下 —— iOS 只认官方包，必须先把 URL 交给它，插件才有机会转发。

---

# English

Redirect Alipay's **碰一碰** (tap-to-pay NFC) trigger to your own second / multi-instance Alipay client.

When you tap a merchant's NFC sticker, iOS always launches the official Alipay — only it passes
the AASA check for `render.alipay.com`; the clone's bundle ID is not in the list. This tweak makes
the official app hand the tap over to your clone the moment it receives the URL.

```
Tap NFC sticker → official Alipay receives URL → tweak intercepts → launches "支付宝2" into the tap-to-pay page
```

## Highlights

- **No `Info.plist` modification, no re-signing of the clone**
- **No setup steps** — works right after install
- The clone's bundle ID is discovered at runtime — works with any multi-instance tool
- Pure `libobjc`, no CydiaSubstrate, no config file
- Source: https://github.com/5hux1n/Alipay2NFC

## Known limitation

On a cold launch the official Alipay briefly appears first — iOS only recognises the official app,
so the URL must reach it before the tweak can forward it.