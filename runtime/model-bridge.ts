import { readFileSync, realpathSync } from "node:fs";
import { resolve } from "node:path";
import { createInterface, type Interface } from "node:readline/promises";
import { fileURLToPath } from "node:url";

import {
  InMemoryCredentialStore,
  contentText,
  type AuthEvent,
  type AuthInteraction,
  type AuthPrompt,
  type CredentialStore,
  type Models,
} from "@earendil-works/pi-ai";
import { registerBunOAuthFlows } from "@earendil-works/pi-ai/bun-oauth";
import { builtinModels } from "@earendil-works/pi-ai/providers/all";

import { FileCredentialStore } from "./credential-store.ts";

registerBunOAuthFlows();

export interface BridgeRequest {
  version: 1;
  prompt: string;
  model: string;
  authPath?: string;
}

interface BridgeSuccess {
  version: 1;
  ok: true;
  text: string;
}

interface DataSuccess {
  version: 1;
  ok: true;
  data: object;
}

interface BridgeFailure {
  version: 1;
  ok: false;
  error: { code: "MODEL_ERROR"; message: string };
}

export type BridgeResponse = BridgeSuccess | DataSuccess | BridgeFailure;

export async function listAvailableModelReferences(models: Models): Promise<string[]> {
  await models.refresh();
  const available = await models.getAvailable();
  return [...new Set(available.map((model) => `${model.provider}/${model.id}`))].sort();
}

export function parseModelReference(reference: string): [string, string] {
  const separator = reference.indexOf("/");
  if (separator < 1 || separator === reference.length - 1) {
    throw new Error(`模型必须使用 provider/model 格式: ${reference}`);
  }
  return [reference.slice(0, separator), reference.slice(separator + 1)];
}

export async function completeWithModels(
  request: BridgeRequest,
  models: Models,
): Promise<BridgeSuccess> {
  if (request.version !== 1 || !request.prompt.trim()) {
    throw new Error("无效的 bridge 请求");
  }
  const [provider, modelId] = parseModelReference(request.model);
  const model = models.getModel(provider, modelId);
  if (!model) {
    throw new Error(`模型不存在: ${request.model}`);
  }

  const response = await models.completeSimple(model, {
    messages: [{ role: "user", content: request.prompt, timestamp: Date.now() }],
  });
  if (response.stopReason === "error" || response.stopReason === "aborted") {
    throw new Error(response.errorMessage || "模型调用失败");
  }

  const text = contentText(response.content).trim();
  if (!text) {
    throw new Error("模型未返回文本");
  }
  return { version: 1, ok: true, text };
}

async function completeCommand(): Promise<BridgeSuccess> {
  const request = JSON.parse(readFileSync(0, "utf8")) as BridgeRequest;
  const credentials: CredentialStore = request.authPath
    ? new FileCredentialStore(request.authPath)
    : new InMemoryCredentialStore();
  return completeWithModels(request, builtinModels({ credentials }));
}

async function providerCommand(args: string[]): Promise<DataSuccess> {
  const [action, providerId, authPath] = args;
  if (!authPath) {
    throw new Error("缺少 Recall 认证文件路径");
  }

  const credentials = new FileCredentialStore(authPath);
  const models = builtinModels({ credentials });
  if (action === "list") {
    return {
      version: 1,
      ok: true,
      data: { providers: await credentials.list() },
    };
  }
  if (!providerId) {
    throw new Error("缺少 provider ID");
  }
  if (action === "logout") {
    await models.logout(providerId);
    return {
      version: 1,
      ok: true,
      data: { provider: providerId, status: "disconnected" },
    };
  }
  if (action === "login") {
    if (providerId !== "openai-codex") {
      throw new Error("当前仅支持 openai-codex OAuth 登录");
    }
    const readline = createInterface({ input: process.stdin, output: process.stderr });
    try {
      await models.login(providerId, "oauth", terminalInteraction(readline));
    } finally {
      readline.close();
    }
    return {
      version: 1,
      ok: true,
      data: { provider: providerId, status: "connected" },
    };
  }
  throw new Error(`未知 provider 操作: ${action}`);
}

async function modelCommand(args: string[]): Promise<DataSuccess> {
  const [action, authPath] = args;
  if (action !== "list") {
    throw new Error(`未知 model 操作: ${action}`);
  }
  if (!authPath) {
    throw new Error("缺少 Recall 认证文件路径");
  }

  const models = builtinModels({ credentials: new FileCredentialStore(authPath) });
  return {
    version: 1,
    ok: true,
    data: { models: await listAvailableModelReferences(models) },
  };
}

function terminalInteraction(readline: Interface): AuthInteraction {
  return {
    prompt: (prompt) => answerPrompt(readline, prompt),
    notify: notifyAuthEvent,
  };
}

async function answerPrompt(readline: Interface, prompt: AuthPrompt): Promise<string> {
  if (prompt.type === "select") {
    printError(`\n${prompt.message}`);
    prompt.options.forEach((option, index) => {
      printError(`  ${index + 1}. ${option.label}`);
    });
    const answer = await readline.question(
      `请输入序号 (1-${prompt.options.length}): `,
      { signal: prompt.signal },
    );
    const selected = prompt.options[Number.parseInt(answer, 10) - 1];
    if (!selected) {
      throw new Error("无效选项");
    }
    return selected.id;
  }
  const placeholder = prompt.placeholder ? ` (${prompt.placeholder})` : "";
  return readline.question(`${prompt.message}${placeholder}: `, {
    signal: prompt.signal,
  });
}

function notifyAuthEvent(event: AuthEvent): void {
  if (event.type === "auth_url") {
    printError(`\n请在浏览器中打开：\n${event.url}`);
    if (event.instructions) printError(event.instructions);
    return;
  }
  if (event.type === "device_code") {
    printError(`\n请在浏览器中打开：\n${event.verificationUri}`);
    printError(`授权码：${event.userCode}`);
    return;
  }
  printError(event.message);
  if (event.type === "info") {
    for (const link of event.links ?? []) {
      printError(`${link.label ?? "更多信息"}：${link.url}`);
    }
  }
}

function printError(message: string): void {
  process.stderr.write(`${message}\n`);
}

async function main(): Promise<void> {
  try {
    const command = process.argv[2];
    const response =
      command === "provider"
        ? await providerCommand(process.argv.slice(3))
        : command === "model"
          ? await modelCommand(process.argv.slice(3))
          : await completeCommand();
    process.stdout.write(JSON.stringify(response));
  } catch (error) {
    const response: BridgeFailure = {
      version: 1,
      ok: false,
      error: {
        code: "MODEL_ERROR",
        message: error instanceof Error ? error.message : String(error),
      },
    };
    process.stdout.write(JSON.stringify(response));
    process.exitCode = 1;
  }
}

if (
  process.argv[1] &&
  realpathSync(resolve(process.argv[1])) === realpathSync(fileURLToPath(import.meta.url))
) {
  await main();
}
