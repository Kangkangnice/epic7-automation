# QQ 消息通知配置教程

开启后，亚卡助手可尝试通过你自己的 QQ 机器人，将任务完成、资源不足或运行失败等结果发送到你的 QQ 私聊。手动停止不发送通知；通知失败不影响游戏任务。此功能可选，不配置也能正常使用助手。

> **使用前请确认：** 本功能依赖腾讯 QQ 机器人的主动消息能力。腾讯[公开接口说明](https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/send.md)同时包含主动推送停止提供的公告及发送额度说明，实际权限须以你的机器人后台和实测为准。配置正确不代表一定能推送。如平台不允许主动消息，请不要反复发送或尝试绕过限制。

## 一、创建自己的 QQ 机器人

1. 打开 [QQ 开放平台](https://q.qq.com/)，登录并按平台要求完成注册及身份认证。
2. 在机器人应用管理中创建机器人，按页面提示选择或申请 QQ 单聊（消息列表单聊）能力。
3. 在机器人开发设置中找到 AppID 和 AppSecret，保存到本机。若平台要求开通事件权限，确认单聊消息事件 `C2C_MESSAGE_CREATE` 可用。
4. 如果机器人尚在开发测试阶段，在平台的沙箱配置中加入自己用于收通知的 QQ 账号，按页面提示扫码打开与机器人的私聊。正式环境则使用已获准的接收账号。

平台后台的菜单名称可能随版本或账号权限而变化。若找不到相应能力，请查看平台实际提供的权限或联系平台客服。**AppSecret 相当于密码，不要发给群友或开发者。**

## 二、获取接收者 OpenID

OpenID 是该机器人识别你的 QQ 账号所使用的标识，不是你的 QQ 号码或交流群号码。不同机器人的 OpenID 不能混用。

如果你已经通过自己的机器人程序收到单聊事件，可直接读取 `C2C_MESSAGE_CREATE` 事件中的 `author.user_openid`，跳到第三节。

如果没有现成的机器人程序，可使用下面的一次性获取方法。此步骤需要另行安装 Python 及腾讯官方 Python SDK；亚卡助手本身仍为免安装版，不需要 Python。以下示例依据[腾讯 botpy 官方单聊示例](https://github.com/tencent-connect/botpy/blob/master/examples/demo_c2c_reply_text.py)编写，需账号具有相应 WebSocket 和单聊事件权限，未在真实机器人上验证。

1. 若电脑没有 Python，从 [Python 官网](https://www.python.org/downloads/windows/) 安装受支持的 Windows Python 版本。
2. 打开 PowerShell，输入以下命令安装 SDK：

   ```powershell
   py -m pip install qq-botpy
   ```

3. 打开记事本，将下面的代码保存为 `get_qq_openid.py`（保存类型选「所有文件」，不要保存成 `.txt`）。无需在文件中填写密钥。

   ```python
   from getpass import getpass
   import botpy

   class OpenIDReader(botpy.Client):
       async def on_ready(self):
           print("机器人已连接，请在手机 QQ 私聊中发送一条消息。", flush=True)

       async def on_c2c_message_create(self, message):
           print("接收者 OpenID：", message.author.user_openid, flush=True)

   appid = input("AppID: ").strip()
   secret = getpass("AppSecret: ").strip()
   sandbox = input("使用沙箱环境？(y/n): ").strip().lower() == "y"
   client = OpenIDReader(intents=botpy.Intents(public_messages=True),
                         is_sandbox=sandbox)
   client.run(appid=appid, secret=secret)
   ```

4. 在该文件所在文件夹打开 PowerShell，运行：

   ```powershell
   py .\get_qq_openid.py
   ```

   输入 AppID、AppSecret，并选择与平台一致的环境。输入密钥时屏幕不显示字符，属于正常现象。
5. 看到连接提示后，用自己的 QQ 向机器人发送一条私聊消息，例如「测试」。复制终端显示的接收者 OpenID，再按 Ctrl+C 结束临时程序。若没有收到事件，先核对单聊权限、沙箱账号和机器人连接状态。

## 三、在 Windows 中配置通知

不需要修改亚卡助手的源代码。

1. 关闭亚卡助手，打开 Windows 开始菜单，搜索「编辑帐户的环境变量」并打开。也可搜索「编辑系统环境变量」，打开后点击「环境变量」。
2. 在上方「用户变量」区域点击「新建」，逐项添加以下三个变量。变量值填写你自己取得的信息，不包含引号。

| 变量名 | 变量值 |
| --- | --- |
| `EPIC7_QQBOT_APP_ID` | 机器人的 AppID |
| `EPIC7_QQBOT_CLIENT_SECRET` | 机器人的 AppSecret |
| `EPIC7_QQBOT_USER_OPENID` | 自己的接收者 OpenID |

如果你的机器人只在沙箱环境中测试，还需添加 `EPIC7_QQBOT_BASE_URL`，变量值为 `https://sandbox.api.sgroup.qq.com`。正式环境无需该变量（默认使用正式接口）；从沙箱切换正式环境时删除该变量。

3. 点击「确定」保存所有窗口，再重新打开 `ArkyAssistant.exe`。如果仍读取不到配置，可注销 Windows 后重新登录再试。

这些变量只保存在你的 Windows 用户账户下。请勿在截图、诊断包或群消息中公开它们；密钥泄露后应及时重置。

## 四、测试通知

1. 确认 QQ 机器人单聊及主动消息权限可用；若 QQ 端提供接收主动消息开关，请确认已允许。
2. 打开游戏和助手，完成环境检测。
3. 选择一个不消耗资源的简单任务，例如「成就领取」，让它自然结束。**不要长按 P 键或点击安全停止来测试**，手动停止不发送通知。
4. 查看手机 QQ 中与该机器人的私聊，确认实际收到任务结果。

通知示例（非实测截图）：

```text
第七史诗：每日任务已完成
任务汇总及各项运行结果……
```

如果未收到，查看助手「运行日志」中的 QQ 通知提示。通知是否成功以 QQ 实际收到为准。

## 五、常见问题

| 现象 | 建议 |
| --- | --- |
| QQ 通知未启用 | 检查三个用户环境变量是否都已填写，重启助手。 |
| 获取凭证失败 | 核对 AppID 和 AppSecret 是否属于同一个机器人，以及网络是否可用。 |
| 获取不到 OpenID | 确认向机器人发的是单聊消息，SDK 已连接且具备相应权限。 |
| 发送失败或被限频 | 检查机器人主动消息权限、接收设置、平台限制，以及正式/沙箱环境是否匹配。 |
| 手动停止后没有通知 | 正常行为。 |
| 想关闭通知 | 删除上述用户环境变量，重新打开助手。 |

如仍有问题，欢迎在亚卡助手 QQ 交流群（**173919378**）反馈错误现象。不要发送 AppSecret、OpenID 或完整环境变量截图。

[返回使用手册](USER_GUIDE.md) · [故障排查与问题反馈](TROUBLESHOOTING.md)
