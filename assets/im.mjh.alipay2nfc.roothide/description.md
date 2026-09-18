# Alipay2NFC

让支付宝「碰一碰」唤起你指定的第二个支付宝客户端。

## 解决的问题

在越狱设备上用 Crane 之类的工具多开支付宝之后，贴商户的碰一碰贴纸时，系统始终唤起官方客户端，第二个账号用不上 NFC 付款。

碰一碰贴纸里是一条指向 `render.alipay.com` 的链接，iOS 按 Universal Link / App Clip 规则投递，而只有官方客户端在该域名下完成过关联声明 —— 多开客户端不在其中，系统不会把链接交给它。

## 做什么

本插件在官方客户端处理这次碰一碰的那一刻接管过来，把付款交给你的多开客户端完成。

## 使用

打开官方支付宝，贴商户的碰一碰贴纸即可。多开客户端会在后台被唤起，无需提前打开，也不用做任何配置。

## 兼容性

- 越狱：rootful、rootless、roothide
- 架构：arm64、arm64e
- 系统：iOS 14 及以上
- 多开客户端：任意多开工具生成的客户端

## 已知限制

冷启动贴纸时，官方客户端会先生效再转交，因此会短暂出现一下。

---

# English

Redirect Alipay's 碰一碰 (NFC tap-to-pay) to the Alipay client of your choice.

## The problem

After duplicating Alipay on a jailbroken device with tools like Crane, tapping a merchant's sticker always launches the official client — the second account can't use NFC payment.

The sticker carries a link to `render.alipay.com`. iOS delivers it as a Universal Link / App Clip, and only the official client has an association claim for that domain, so iOS never hands the link to the clone.

## What it does

The tweak takes over at the moment the official client processes the tap and hands the payment to your chosen client.

## Usage

Open the official Alipay and tap the merchant's sticker. The second client is brought up in the background — no need to open it first, and no configuration is required.

## Compatibility

- Jailbreak: rootful, rootless, roothide
- Architecture: arm64, arm64e
- iOS: 14.0+
- Second client: any created by any multi-instance tool

## Known limitation

On a cold launch the official client briefly takes effect before handing over, so it appears for a moment.