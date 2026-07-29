from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationChannelDefinition:
    key: str
    implemented: bool
    supports_signing: bool


@dataclass(frozen=True)
class NotificationTemplateDefinition:
    key: str
    version: str
    notification_type: str
    target: str
    title: str


NOTIFICATION_CHANNEL_CATALOG = (
    NotificationChannelDefinition("dingtalk", implemented=True, supports_signing=True),
    NotificationChannelDefinition("telegram", implemented=True, supports_signing=False),
    NotificationChannelDefinition("feishu", implemented=False, supports_signing=True),
)
NOTIFICATION_CHANNELS = {
    definition.key: definition for definition in NOTIFICATION_CHANNEL_CATALOG
}
IMPLEMENTED_NOTIFICATION_CHANNELS = tuple(
    definition.key for definition in NOTIFICATION_CHANNEL_CATALOG if definition.implemented
)

NOTIFICATION_TEMPLATE_CATALOG = (
    NotificationTemplateDefinition(
        "service_firing", "v1", "firing", "service", "🔴 服务异常"
    ),
    NotificationTemplateDefinition(
        "service_resolved", "v1", "resolved", "service", "✅ 服务已恢复"
    ),
    NotificationTemplateDefinition(
        "agent_firing", "v1", "firing", "agent", "🔴 VPS 失联"
    ),
    NotificationTemplateDefinition(
        "agent_resolved", "v1", "resolved", "agent", "✅ VPS 已恢复连接"
    ),
)
NOTIFICATION_TEMPLATES = {
    (definition.key, definition.version): definition
    for definition in NOTIFICATION_TEMPLATE_CATALOG
}
CURRENT_NOTIFICATION_TEMPLATE_VERSION = "v1"


def template_key(source: str, notification_type: str) -> str:
    target = "agent" if source == "agent" else "service"
    key = f"{target}_{notification_type}"
    if (key, CURRENT_NOTIFICATION_TEMPLATE_VERSION) not in NOTIFICATION_TEMPLATES:
        raise ValueError("unsupported notification template")
    return key
