/**
 * Cloudflare Worker — StartupRadar 텔레그램 Webhook Handler
 *
 * 지원 명령어:
 *   /run    → GitHub Actions workflow_dispatch 트리거 (dry_run: false)
 *   /dry    → GitHub Actions workflow_dispatch 트리거 (dry_run: true)
 *   /stop   → 정기 전송 중지
 *   /share  → 여러 사람이 결과를 받는 설정 안내
 *   /stage  → 동아리 단계 변경 (팀빌딩|아이디어|MVP|초기매출)
 *   /id     → 내 Telegram ID 확인
 *   /status → 상태 확인
 *   /help   → 명령어 안내
 *
 * 환경변수 (Cloudflare Worker Secrets):
 *   GITHUB_TOKEN        - GitHub Personal Access Token (workflow:write 권한)
 *   GITHUB_OWNER        - GitHub 사용자명 또는 조직명
 *   GITHUB_REPO         - 저장소 이름
 *   TELEGRAM_BOT_TOKEN  - 텔레그램 봇 토큰
 *   TELEGRAM_CHAT_ID    - 결과를 받을 개인/그룹/채널 chat_id 또는 @channel_username
 *   TELEGRAM_ADMIN_CHAT_ID - 명령어를 허용할 관리자 개인 from.id (없으면 TELEGRAM_CHAT_ID 사용)
 */

const VALID_STAGES = ["팀빌딩", "아이디어", "MVP", "초기매출"];

const BOT_COMMANDS = [
  { command: "run", description: "지금 즉시 수집하고 텔레그램으로 발송" },
  { command: "dry", description: "발송 없이 수집만 테스트" },
  { command: "stop", description: "정기 전송 중지" },
  { command: "share", description: "여러 사람이 결과를 받는 설정 안내" },
  { command: "stage", description: "동아리 단계 변경" },
  { command: "id", description: "내 Telegram ID 확인" },
  { command: "status", description: "봇 상태 확인" },
  { command: "help", description: "명령어 안내" },
];

const HEALTH_TEXT = "StartupRadar Telegram webhook is live. Send /id to the bot to check your Telegram from.id.";

const SHARE_HELP_TEXT =
  "📣 여러 사람이 결과를 받게 하려면\n\n" +
  "1. 텔레그램 채널 또는 그룹을 만듭니다.\n" +
  "2. 이 봇을 채널 관리자 또는 그룹 멤버로 추가합니다.\n" +
  "3. 채널이면 봇에 메시지 게시 권한을 줍니다.\n" +
  "4. Cloudflare Worker Secret의 TELEGRAM_CHAT_ID를 그 채널/그룹 ID 또는 공개 채널 username으로 바꿉니다.\n" +
  "5. TELEGRAM_ADMIN_CHAT_ID에는 관리자 개인 from.id를 넣습니다.\n\n" +
  "이렇게 하면 결과는 여러 사람이 보는 곳으로 전송되고, /run, /dry, /stop 같은 명령은 관리자만 사용할 수 있습니다.";

export default {
  async fetch(request, env) {
    if (request.method === "GET") {
      return new Response(HEALTH_TEXT, {
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    try {
      const message = getTelegramMessage(update);
      const updateType = getUpdateType(update);
      if (!message) {
        console.log("Telegram update ignored: no message-like payload", {
          updateId: update?.update_id,
          updateType,
        });
        return new Response("OK");
      }

      const chatId = message.chat?.id;
      const fromId = message.from?.id;
      const senderChatId = message.sender_chat?.id;
      const text = (message.text || message.caption || "").trim();
      const command = normalizeCommand(text);

      console.log("Telegram update received", {
        updateId: update?.update_id,
        updateType,
        command,
        chatId,
        fromId,
        senderChatId,
      });

      if (isIdCommand(command)) {
        await sendTelegram(env, chatId, buildIdHelpText(fromId, chatId, senderChatId));
        return new Response("OK");
      }

      // 허용된 관리자 개인 ID 외 무시. 그룹 명령은 chat.id가 그룹 ID라서 from.id를 기준으로 봅니다.
      const adminChatIds = parseAdminChatIds(env);
      if (!isAdmin(fromId, adminChatIds)) {
        return new Response("OK");
      }

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

        case "/stage": {
          const stage = text.split(/\s+/).slice(1).join(" ").trim();
          if (VALID_STAGES.includes(stage)) {
            await triggerStageWorkflow(env, stage);
            await sendTelegram(env, chatId, `⏳ 단계 변경 중... '${stage}'(으)로 변경 요청했습니다.`);
          } else {
            await sendTelegram(env, chatId, `사용법: /stage [${VALID_STAGES.join("|")}]`);
          }
          break;
        }

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
            "/id — 내 Telegram ID 확인\n" +
            "/stage [단계] — 동아리 단계 변경\n" +
            `     └ 단계: ${VALID_STAGES.join(" | ")}\n` +
            "/status — 봇 상태 확인\n" +
            "/help — 이 메시지 보기",
            "Markdown"
          );
          break;

        default:
          await sendTelegram(env, chatId, "❓ 알 수 없는 명령어입니다. /help 를 입력하세요.");
      }
    } catch (error) {
      console.error("Telegram webhook failed", {
        message: error?.message || String(error),
      });
      return new Response("Webhook Error", { status: 500 });
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

async function triggerStageWorkflow(env, stage) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/update_stage.yml/dispatches`;

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
        stage,
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
  if (chatId === undefined || chatId === null) {
    throw new Error("Cannot send Telegram message: missing chatId");
  }

  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;

  const payload = { chat_id: chatId, text };
  if (parseMode) payload.parse_mode = parseMode;

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await res.text();
    console.error("Telegram sendMessage failed", {
      status: res.status,
      body,
    });
    throw new Error(`Telegram API error ${res.status}: ${body}`);
  }
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

function getTelegramMessage(update) {
  return (
    update?.message ||
    update?.edited_message ||
    update?.channel_post ||
    update?.edited_channel_post
  );
}

function getUpdateType(update) {
  if (!update || typeof update !== "object") return "unknown";
  return [
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "callback_query",
    "inline_query",
  ].find((key) => Boolean(update[key])) || "unknown";
}

function buildIdHelpText(fromId, chatId, senderChatId = null) {
  const fromText = fromId ?? "없음";
  const senderChatText = senderChatId ?? "없음";
  return (
    "🪪 Telegram ID 확인\n\n" +
    `from.id: ${fromText}\n` +
    `chat.id: ${chatId ?? "없음"}\n\n` +
    `sender_chat.id: ${senderChatText}\n\n` +
    "Cloudflare Worker Secret의 TELEGRAM_ADMIN_CHAT_ID에는 from.id 값을 넣으세요.\n" +
    "from.id가 없음으로 나오면 채널 글로 들어온 것이므로, 봇과의 개인 채팅에서 /id를 보내세요.\n" +
    "TELEGRAM_CHAT_ID는 결과를 받을 채널/그룹/개인 대상으로 둡니다."
  );
}

function isIdCommand(command) {
  return command === "/id" || command === "/whoami" || command === "id" || command === "whoami";
}

function normalizeCommand(text) {
  return (text.split(/\s+/)[0] || "").toLowerCase().split("@")[0];
}
