import Link from "next/link";
import { getNotificationConfiguration, getNotificationTests, type NotificationTest } from "@/lib/api";
import { NotificationTestPanel } from "./test-panel";

export const dynamic = "force-dynamic";

const issueText: Record<string, string> = {
  dingtalk_webhook_missing: "尚未配置 DINGTALK_WEBHOOK_URL，通知不会发送。",
  telegram_bot_token_missing: "已启用 Telegram，但尚未配置 TELEGRAM_BOT_TOKEN。",
  telegram_chat_id_missing: "已启用 Telegram，但尚未配置 TELEGRAM_CHAT_ID。",
  console_public_url_not_https: "生产环境的 CONSOLE_PUBLIC_URL 必须使用 HTTPS。",
};

const channelName = {
  dingtalk: "钉钉",
  telegram: "Telegram",
  feishu: "飞书（预留）",
};

export default async function NotificationSettingsPage() {
  let configuration = null;
  let tests: NotificationTest[] = [];
  try {
    [configuration, tests] = await Promise.all([
      getNotificationConfiguration(),
      getNotificationTests(),
    ]);
  } catch {
    return (
      <main>
        <section className="hero compact">
          <div className="eyebrow"><span /> M6.3 · NOTIFICATIONS</div>
          <h1>通知<span>就绪</span></h1>
          <p>无法读取通知配置状态；未展示任何缓存值或凭据。</p>
          <Link className="back" href="/">← 返回控制台</Link>
        </section>
        <div className="empty error" role="alert">控制平面暂时不可用，请检查 API 和管理认证配置。</div>
      </main>
    );
  }
  return (
    <main>
      <section className="hero compact">
        <div className="eyebrow"><span /> M6.3 · NOTIFICATIONS</div>
        <h1>通知<span>就绪</span></h1>
        <p>只显示配置状态，不回显 Webhook、签名密钥或其他凭据。</p>
        <Link className="back" href="/">← 返回控制台</Link>
      </section>

      <section className="notification-readiness" aria-label="通知配置状态">
        <div className={`notification-state ${configuration.ready ? "ready" : "attention"}`}>
          <span>{configuration.ready ? "READY" : "NEEDS CONFIGURATION"}</span>
          <strong>{configuration.ready ? "通知链已具备发送条件" : "请完成下列配置"}</strong>
        </div>
        <div className="summary-grid">
          {configuration.channels.map((channel) => (
            <div key={channel.channel}>
              <span>{channelName[channel.channel]}</span>
              <strong>{!channel.implemented ? "尚未实现" : channel.enabled ? (channel.configured ? "已启用" : "缺少配置") : "未选择"}</strong>
            </div>
          ))}
          <div><span>控制台链接</span><strong>{configuration.console_links_https ? "HTTPS" : "非 HTTPS"}</strong></div>
        </div>
        {configuration.issues.length > 0 && (
          <ul className="notification-issues">
            {configuration.issues.map((issue) => <li key={issue}>{issueText[issue] ?? issue}</li>)}
          </ul>
        )}
      </section>

      <section className="section">
        <div className="section-title"><h2>引导式配置</h2><span>environment only</span></div>
        <div className="notification-guide">
          <p>在服务器的 <code>deploy/.env.production</code> 中设置以下变量，再通过现有部署流程重建 API。凭据只注入 API 容器，不进入浏览器、Agent、数据库备份或页面 HTML。</p>
          <ol>
            <li><code>NOTIFICATION_CHANNELS</code>：从内置白名单选择，例如 <code>dingtalk,telegram</code>；不接受任意适配器或 URL。</li>
            <li><code>DINGTALK_WEBHOOK_URL</code>：钉钉自定义机器人的完整 Webhook。</li>
            <li><code>DINGTALK_SECRET</code>：机器人启用“加签”时设置；未启用加签可留空。</li>
            <li><code>TELEGRAM_BOT_TOKEN</code> 与 <code>TELEGRAM_CHAT_ID</code>：仅在选择 Telegram 时设置；API 地址固定为 Telegram 官方端点。</li>
            <li><code>CONTROL_PLANE_DOMAIN</code>：生产 Compose 据此生成 HTTPS 控制台链接。</li>
          </ol>
          <p>页面仍不提供秘密录入或运行时改配置。下方测试入口只发送服务端固定消息，并单独执行限速、幂等和审计。</p>
        </div>
      </section>

      <section className="section">
        <div className="section-title"><h2>固定模板目录</h2><span>{configuration.templates.length} templates</span></div>
        <div className="notification-templates">
          {configuration.templates.map((template) => (
            <article key={`${template.key}:${template.version}`}>
              <span>{template.target} · {template.notification_type}</span>
              <strong>{template.title}</strong>
              <small>{template.key} · {template.version} · {template.supported_channels.join(" + ")}</small>
            </article>
          ))}
        </div>
        <p className="section-copy">事件标题、目标和详情仍按不可信文本转义；模板不接受模型生成内容，也不能产生 Operation。</p>
      </section>

      {configuration.channels
        .filter((channel) => channel.implemented && channel.enabled)
        .map((channel) => (
          <NotificationTestPanel
            key={channel.channel}
            channel={channel.channel as "dingtalk" | "telegram"}
            channelLabel={channelName[channel.channel]}
            configured={channel.configured}
            enabled={configuration.test_messages_enabled}
            cooldownSeconds={configuration.test_cooldown_seconds}
            initialTests={tests.filter((test) => test.channel === channel.channel)}
          />
        ))}

      <footer>
        <span>delivery</span> firing + resolved <i /> <span>retry</span> 最多 {configuration.max_delivery_attempts} 次 <i /> <span>stale reclaim</span> {configuration.sending_stale_seconds}s
      </footer>
    </main>
  );
}
