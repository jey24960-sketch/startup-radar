/**
 * Cloudflare Worker — StartupRadar 텔레그램 Webhook Handler
 *
 * 지원 명령어:
 *   /run    → GitHub Actions workflow_dispatch 트리거 (dry_run: false)
 *   /dry    → GitHub Actions workflow_dispatch 트리거 (dry_run: true)
 *   /stop   → 정기 전송 중지
 *   /share  → 여러 사람이 결과를 받는 설정 안내
 *   /status → 상태 확인
 *   /help   → 명령어 안내
 *
 * 환경변수 (Cloudflare Worker Secrets):
 *   GITHUB_TOKEN        - GitHub Personal Access Token (workflow:write 권한)
 *   GITHUB_OWNER        - GitHub 사용자명 또는 조직명
 *   GITHUB_REPO         - 저장소 이름
 *   TELEGRAM_BOT_TOKEN  - 텔레그램 봇 토큰
 *   TELEGRAM_CHAT_ID    - 결과를 받을 개인/그룹/채널 chat_id 또는 @channel_username
 *   TELEGRAM_ADMIN_CHAT_ID - 명령어를 허용할 관리자 개인 chat_id (없으면 TELEGRAM_CHAT_ID 사용)
 */

const BOT_COMMANDS = [
  { command: "run", description: "지금 즉시 수집하고 텔레그램으로 발송" },
  { command: "dry", description: "발송 없이 수집만 테스트" },
  { command: "stop", description: "정기 전송 중지" },
  { command: "share", description: "여러 사람이 결과를 받는 설정 안내" },
  { command: "status", description: "봇 상태 확인" },
  { command: "help", description: "명령어 안내" },
];

const SHARE_HELP_TEXT =
  "📣 여러 사람이 결과를 받게 하려면\n\n" +
  "1. 텔레그램 채널 또는 그룹을 만듭니다.\n" +
  "2. 이 봇을 채널 관리자 또는 그룹 멤버로 추가합니다.\n" +
  "3. 채널이면 봇에 메시지 게시 권한을 줍니다.\n" +
  "4. Cloudflare Worker Secret의 TELEGRAM_CHAT_ID를 그 채널/그룹 ID 또는 공개 채널 username으로 바꿉니다.\n" +
  "5. TELEGRAM_ADMIN_CHAT_ID에는 관리자 개인 chat id를 넣습니다.\n\n" +
  "이렇게 하면 결과는 여러 사람이 보는 곳으로 전송되고, /run, /dry, /stop 같은 명령은 관리자만 사용할 수 있습니다.";

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    const message = update?.message;
    if (!message) return new Response("OK");

    const chatId = message.chat?.id;
    const fromId = message.from?.id;
    const text = (message.text || "").trim();
    const adminChatIds = parseAdminChatIds(env);

    // 허용된 관리자 개인 ID 외 무시. 그룹 명령은 chat.id가 그룹 ID라서 from.id를 기준으로 봅니다.
    if (!isAdmin(fromId, adminChatIds)) {
      return new Response("OK");
    }

    const command = normalizeCommand(text);

    switch (command) {
      case "/run":
        await triggerWorkflow(env, false);
        await sendTelegram(env, chatId, "✅ StartupRadar 실행을 요청했습니다. (dry_run: false)");
        break;

      case "/dry":
        await triggerWorkflow(env, true);
        await sendTelegram(env, chatId, "🧪 StartupRadar 테스트 실행을 요청했습니다. (dry_run: true, 발송 없음)");
        break;

      case "/stop":
        await triggerAutoRunControl(env, false);
        await sendTelegram(env, chatId, "🛑 정기 전송을 중지합니다. 화/금 자동 실행은 꺼지고, 수동 /run은 계속 사용할 수 있습니다.");
        break;

      case "/share":
        await sendTelegram(env, chatId, SHARE_HELP_TEXT);
        break;

      case "/status":
        await sendTelegram(env, chatId, "🟢 StartupRadar 정상 작동 중");
        break;

      case "/help":
        await setTelegramCommands(env).catch(() => {});
        await sendTelegram(
          env,
          chatId,
          "📋 *StartupRadar 명령어 목록*\n\n" +
          "/run — 즉시 실행 (텔레그램 발송 포함)\n" +
          "/dry — 테스트 실행 (발송 없음)\n" +
          "/stop — 정기 전송 중지 (수동 /run은 유지)\n" +
          "/share — 여러 사람이 결과를 받는 설정 안내\n" +
          "/status — 봇 상태 확인\n" +
          "/help — 이 메시지 보기",
          "Markdown"
        );
        break;

      default:
        await sendTelegram(env, chatId, "❓ 알 수 없는 명령어입니다. /help 를 입력하세요.");
    }

    return new Response("OK");
  },
};

async function triggerWorkflow(env, dryRun) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/startup_radar.yml/dispatches`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "StartupRadar-CloudflareWorker",
    },
    body: JSON.stringify({
      ref: "main",
      inputs: {
        dry_run: String(dryRun),
      },
    }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`GitHub API error ${res.status}: ${body}`);
  }
}

async function triggerAutoRunControl(env, enabled) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/update_auto_run.yml/dispatches`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "StartupRadar-CloudflareWorker",
    },
    body: JSON.stringify({
      ref: "main",
      inputs: {
        enabled: String(enabled),
      },
    }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`GitHub API error ${res.status}: ${body}`);
  }
}

async function sendTelegram(env, chatId, text, parseMode = null) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;

  const payload = { chat_id: chatId, text };
  if (parseMode) payload.parse_mode = parseMode;

  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function setTelegramCommands(env) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/setMyCommands`;

  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ commands: BOT_COMMANDS }),
  });
}

function parseAdminChatIds(env) {
  const raw = env.TELEGRAM_ADMIN_CHAT_ID || env.TELEGRAM_CHAT_ID || "";
  return String(raw)
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function isAdmin(fromId, adminChatIds) {
  if (fromId === undefined || fromId === null || adminChatIds.length === 0) {
    return false;
  }
  return adminChatIds.includes(String(fromId));
}

function normalizeCommand(text) {
  return (text.split(/\s+/)[0] || "").toLowerCase().split("@")[0];
}
