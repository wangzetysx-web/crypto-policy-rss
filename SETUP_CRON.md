# 外部定时服务设置详细步骤

## 第一步：创建 GitHub Personal Access Token（预计 5 分钟）

### 1.1 打开 Token 创建页面

1. 在浏览器中打开：https://github.com/settings/tokens
2. 如果没有登录，先登录你的 GitHub 账号

### 1.2 创建新 Token

1. 点击页面右上角的 **"Generate new token"** 按钮
2. 在下拉菜单中选择 **"Generate new token (classic)"**
   - ⚠️ 注意：选择 "classic"，不是 "fine-grained"

### 1.3 填写 Token 信息

你会看到一个表单，按如下填写：

#### Note（备注）
```
RSS Cron Trigger
```
这是给你自己看的备注，方便以后识别这个 token 的用途

#### Expiration（过期时间）
- 下拉菜单中选择：**"No expiration"**（不过期）
- 或者选择 **"Custom"** → 设置 1 年后过期

#### Select scopes（选择权限）
这是最重要的部分！

1. 找到 **"repo"** 这一行（第一个大分类）
2. 点击 **"repo"** 左边的复选框，勾选它
3. ✅ 确保 **"repo"** 及其下面所有子选项都被勾选（应该有 8-9 个子选项）

子选项包括：
- repo:status
- repo_deployment
- public_repo
- repo:invite
- security_events
- 等等...（全部自动勾选）

**其他权限不需要勾选**

### 1.4 生成 Token

1. 滚动到页面最底部
2. 点击绿色按钮 **"Generate token"**

### 1.5 保存 Token

⚠️ **非常重要！**

1. 页面会显示一个以 `ghp_` 开头的长字符串，例如：
   ```
   ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

2. **立即复制这个 token！**
   - 点击 token 右边的复制图标 📋
   - 或者手动选中全部文本然后 Ctrl+C

3. **将 token 粘贴到一个安全的地方**（记事本、密码管理器等）
   - ⚠️ 关闭这个页面后，你将无法再次查看这个 token
   - 如果丢失，只能删除重新生成

4. 保存后，这一步完成 ✅

---

## 第二步：注册 cron-job.org 账号（预计 3 分钟）

### 2.1 打开注册页面

1. 在浏览器中打开：https://cron-job.org/en/
2. 点击页面右上角的 **"Sign up"** 按钮

### 2.2 填写注册信息

1. **Email address**（邮箱）
   - 输入你的常用邮箱
   - 建议使用 Gmail 或其他稳定的邮箱

2. **Password**（密码）
   - 设置一个安全的密码
   - 至少 8 位，包含字母和数字

3. **Repeat password**（重复密码）
   - 再次输入相同的密码

4. 勾选 **"I accept the Terms of Service"**（接受服务条款）

5. 点击 **"Sign up"** 按钮

### 2.3 验证邮箱

1. 打开你的邮箱
2. 找到来自 cron-job.org 的验证邮件
   - 邮件主题通常是："Please verify your email address"
   - 如果没收到，检查垃圾邮件文件夹

3. 点击邮件中的验证链接
4. 浏览器会自动跳转并显示 "Email verified"

### 2.4 登录账号

1. 返回 https://cron-job.org
2. 点击右上角 **"Log in"**
3. 输入你的邮箱和密码
4. 点击 **"Log in"** 按钮

登录成功后，你会看到 Dashboard（控制面板）

---

## 第三步：创建定时任务（预计 5 分钟）

### 3.1 开始创建

1. 登录后，在左侧菜单点击 **"Cronjobs"**
2. 点击右上角蓝色按钮 **"Create cronjob"**

### 3.2 填写基本信息

你会看到一个创建表单，按如下填写：

#### Title（标题）
```
RSS News Daily Push - 8:00 AM Beijing Time
```

#### Address/URL
```
https://api.github.com/repos/wangzetysx-web/crypto-policy-rss/actions/workflows/daily.yml/dispatches
```
⚠️ 注意：直接复制粘贴，确保没有多余的空格

### 3.3 设置执行时间

找到 **"Schedule"** 部分：

#### Type（类型）
- 选择：**"Every day"**（每天）

#### Time（时间）
- 输入：**`00:00`**
- 或者使用时间选择器选择 0 时 0 分

#### Time zone（时区）⚠️ 重要！
1. 点击下拉菜单
2. 搜索或滚动找到：**"Asia/Shanghai (UTC+8)"**
3. 选择它

⚠️ 确认：时区显示为 **Asia/Shanghai**，时间显示为 **00:00**

### 3.4 设置请求方法

找到 **"Request settings"** 部分：

#### Request method（请求方法）
- 点击下拉菜单
- 选择：**"POST"**

### 3.5 添加请求头（Headers）

找到 **"HTTP headers"** 部分：

1. 点击 **"+ Add header"** 按钮

**第一个 Header：**
- Name（名称）：
  ```
  Accept
  ```
- Value（值）：
  ```
  application/vnd.github+json
  ```

2. 再次点击 **"+ Add header"**

**第二个 Header：**
- Name（名称）：
  ```
  Authorization
  ```
- Value（值）：
  ```
  Bearer ghp_你的Token在这里
  ```
  ⚠️ 重要：
  - "Bearer" 后面有一个空格
  - 将 "ghp_你的Token在这里" 替换为你在第一步保存的完整 token
  - 例如：`Bearer ghp_1234567890abcdefghijklmnopqrstuvwxyz`

3. 再次点击 **"+ Add header"**

**第三个 Header：**
- Name（名称）：
  ```
  X-GitHub-Api-Version
  ```
- Value（值）：
  ```
  2022-11-28
  ```

现在应该有 3 个 headers 了。

### 3.6 设置请求体（Body）

找到 **"Request body"** 部分：

#### Content-Type
- 点击下拉菜单
- 选择：**"application/json"**

#### Body
- 在文本框中输入：
  ```json
  {"ref":"main","inputs":{"dry_run":"false","log_level":"INFO"}}
  ```
  ⚠️ 直接复制粘贴，确保是一行，没有换行

### 3.7 设置通知（可选）

找到 **"Notifications"** 部分：

- 勾选 **"Send me an email when execution fails"**
  （当执行失败时发送邮件通知）

### 3.8 保存任务

1. 检查所有信息是否正确
2. 滚动到页面底部
3. 点击蓝色按钮 **"Create cronjob"**

成功后会自动跳转到任务列表页面。

---

## 第四步：测试定时任务（预计 2 分钟）

### 4.1 找到刚创建的任务

1. 在任务列表中，找到你刚创建的任务：
   - 标题是："RSS News Daily Push - 8:00 AM Beijing Time"

2. 在这一行，你会看到几个按钮

### 4.2 立即执行测试

1. 点击右侧的 **"▶"** 图标（播放按钮）
   - 或者点击 **"Execute now"** 按钮

2. 等待 3-5 秒

### 4.3 查看执行结果

#### 在 cron-job.org 上查看

1. 点击任务名称，进入详情页面
2. 查看 **"Execution history"** 部分
3. 最新的一条执行记录应该显示：
   - Status: **204** 或 **200**（绿色，表示成功）
   - Duration: 通常 < 3 秒

如果显示其他状态码：
- **401/403**：Token 权限不足或错误
  - 检查：Token 是否正确复制
  - 检查：Token 是否有 "repo" 权限
- **404**：URL 错误
  - 检查：URL 是否正确复制
- **422**：请求体格式错误
  - 检查：Body JSON 格式是否正确

#### 在 GitHub 上验证

1. 打开浏览器，访问：
   ```
   https://github.com/wangzetysx-web/crypto-policy-rss/actions
   ```

2. 你应该能看到一条新的 workflow 运行记录
   - 名称："加密政策 RSS 每日推送"
   - 触发方式：workflow_dispatch
   - 状态：正在运行或已完成

3. 点击进入查看详细日志

### 4.4 确认成功

如果满足以下条件，说明配置成功：

✅ cron-job.org 显示状态码 200 或 204
✅ GitHub Actions 有新的运行记录
✅ 工作流执行成功（绿色勾 ✓）

---

## 第五步：最终确认（预计 1 分钟）

### 5.1 检查定时任务状态

1. 返回 cron-job.org 的任务列表
2. 确认你的任务：
   - Status（状态）：**Enabled**（已启用，绿色）
   - Next execution（下次执行）：应该显示明天 00:00 (Asia/Shanghai)

### 5.2 设置完成！

🎉 恭喜！设置完成！

从现在开始，系统将：
- ✅ 每天北京时间 **08:00:00** 准时触发
- ✅ 自动抓取 13 个 RSS 源的最新新闻
- ✅ 根据关键词过滤内容
- ✅ 翻译为中文
- ✅ 发送到企业微信群

延迟：通常 < 10 秒

---

## 常见问题排查

### 问题 1：cron-job.org 显示 401/403 错误

**原因**：Token 权限不足或错误

**解决**：
1. 检查 Authorization header 的值
2. 确保格式是：`Bearer ghp_你的token`（Bearer 和 token 之间有空格）
3. 重新创建 Token，确保勾选了 "repo" 权限

### 问题 2：cron-job.org 显示 404 错误

**原因**：URL 错误

**解决**：
1. 检查 URL 是否完整复制
2. 确保没有多余的空格或换行
3. 正确的 URL：
   ```
   https://api.github.com/repos/wangzetysx-web/crypto-policy-rss/actions/workflows/daily.yml/dispatches
   ```

### 问题 3：GitHub Actions 没有触发

**原因**：请求体格式错误

**解决**：
1. 检查 Body 的 JSON 格式
2. 确保 Content-Type 是 `application/json`
3. 正确的 Body：
   ```json
   {"ref":"main","inputs":{"dry_run":"false","log_level":"INFO"}}
   ```

### 问题 4：时间不对

**原因**：时区设置错误

**解决**：
1. 编辑任务
2. 确认 Timezone 是 `Asia/Shanghai (UTC+8)`
3. 确认 Time 是 `00:00`

---

## 监控和维护

### 日常监控

1. **查看 cron-job.org**
   - 登录：https://cron-job.org
   - 查看执行历史
   - 检查是否有失败记录

2. **查看 GitHub Actions**
   - 访问：https://github.com/wangzetysx-web/crypto-policy-rss/actions
   - 查看每日运行记录
   - 检查是否有错误

### Token 过期处理

如果你设置了 Token 过期时间：

1. 过期前会收到 GitHub 邮件提醒
2. 重新创建一个新 Token（按第一步操作）
3. 在 cron-job.org 编辑任务
4. 更新 Authorization header 的值
5. 保存

---

## 需要帮助？

如果在设置过程中遇到任何问题，提供以下信息：

1. 在哪一步遇到问题？
2. 具体的错误信息是什么？
3. 截图（如果可以）

我会帮你解决！
