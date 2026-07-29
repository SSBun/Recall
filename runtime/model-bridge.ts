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
export type LoginSessionEvent = Record<string, unknown>;

export interface LoginSessionController {
  controller: AbortController;
  interaction: AuthInteraction;
  handleLine(line: string): void;
}

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

export function createLoginSessionController(
  method: string,
  emit: (event: LoginSessionEvent) => void = emitEvent,
): LoginSessionController {
  const controller = new AbortController();
  let methodAnswered = false;
  let resolveCode: ((code: string) => void) | null = null;
  let pendingCode = nextCodePromise();

  function nextCodePromise(): Promise<string> {
    return new Promise<string>((resolve) => {
      resolveCode = resolve;
    });
  }

  function resolvePendingCode(code: string): void {
    const callback = resolveCode;
    resolveCode = null;
    if (callback) {
      callback(code);
    }
  }

  async function prompt(promptInput: AuthPrompt): Promise<string> {
    if (!methodAnswered && promptInput.type === "select") {
      methodAnswered = true;
      return selectMethod(promptInput, method);
    }
    if (
      promptInput.type === "text" ||
      promptInput.type === "secret" ||
      promptInput.type === "manual_code"
    ) {
      emit({ type: "waiting", prompt: promptInput.message });
      const code = await pendingCode;
      pendingCode = nextCodePromise();
      if (controller.signal.aborted) {
        throw new Error("cancelled");
      }
      return code;
    }
    throw new Error(`unexpected prompt type: ${promptInput.type}`);
  }

  function notify(event: AuthEvent): void {
    if (event.type === "auth_url") {
      emit({
        type: "auth_url",
        url: event.url,
        instructions: event.instructions ?? undefined,
      });
      return;
    }
    if (event.type === "device_code") {
      emit({
        type: "device_code",
        verification_uri: event.verificationUri,
        user_code: event.userCode,
        interval_seconds: event.intervalSeconds ?? undefined,
        expires_in_seconds: event.expiresInSeconds ?? undefined,
      });
      return;
    }
    emit({ type: event.type, message: event.message });
  }

  function handleLine(line: string): void {
    try {
      const payload = JSON.parse(line) as { type?: string; cancel?: boolean; code?: unknown };
      if (payload.cancel || payload.type === "cancel") {
        controller.abort();
        resolvePendingCode("");
        return;
      }
      if ((payload.type === "code" || payload.code !== undefined) && typeof payload.code === "string") {
        resolvePendingCode(payload.code);
      }
    } catch {
      // ignore invalid control lines
    }
  }

  return {
    controller,
    interaction: {
      signal: controller.signal,
      prompt,
      notify,
    },
    handleLine,
  };
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

async function loginSessionCommand(args: string[]): Promise<void> {
  const [providerId, authPath, method] = args;
  if (!providerId || !authPath || !method) {
    emitEvent({ type: "error", message: "usage: provider login-session <provider> <authPath> <method>" });
    process.exitCode = 1;
    return;
  }
  if (method !== "browser" && method !== "device_code") {
    emitEvent({ type: "error", message: `method 只能是 browser 或 device_code: ${method}` });
    process.exitCode = 1;
    return;
  }
  if (providerId !== "openai-codex") {
    emitEvent({ type: "error", message: "当前仅支持 openai-codex OAuth 登录" });
    process.exitCode = 1;
    return;
  }

  const credentials = new FileCredentialStore(authPath);
  const models = builtinModels({ credentials });
  const session = createLoginSessionController(method);
  const readline = createInterface({ input: process.stdin });
  const closeReadline = () => {
    try {
      readline.close();
    } catch {
      // ignored
    }
  };
  session.controller.signal.addEventListener("abort", closeReadline, { once: true });
  readline.on("line", session.handleLine);

  try {
    await models.login(providerId, "oauth", session.interaction);
    emitEvent({ type: "completed" });
  } catch (error) {
    if (isCancelError(error) || session.controller.signal.aborted) {
      emitEvent({ type: "cancelled" });
      return;
    }
    emitEvent({ type: "error", message: errorMessage(error) });
    process.exitCode = 1;
  } finally {
    closeReadline();
  }
}

function selectMethod(prompt: Extract<AuthPrompt, { type: "select" }>, method: string): string {
  const normalizedMethod = method === "device_code" ? "device-code" : method;
  const selected = prompt.options.find((option) => {
    const optionId = option.id.toLowerCase();
    const optionLabel = option.label.toLowerCase();
    return (
      optionId === method ||
      optionId === normalizedMethod ||
      optionLabel.includes(method.replace("_", " ")) ||
      optionLabel.includes(normalizedMethod.replace("-", " "))
    );
  });
  if (!selected) {
    throw new Error(`OAuth method not available: ${method}`);
  }
  return selected.id;
}

function emitEvent(event: LoginSessionEvent): void {
  process.stdout.write(JSON.stringify(event) + "\n");
}

function isCancelError(error: unknown): boolean {
  return error instanceof Error && (error.message === "cancelled" || error.name === "AbortError");
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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
    if (event.instructions) {
      printError(event.instructions);
    }
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
    if (command === "provider") {
      const action = process.argv[3];
      if (action === "login-session") {
        await loginSessionCommand(process.argv.slice(4));
        return;
      }
      const response = await providerCommand(process.argv.slice(3));
      process.stdout.write(JSON.stringify(response));
      return;
    }
    const response =
      command === "model"
        ? await modelCommand(process.argv.slice(3))
        : await completeCommand();
    process.stdout.write(JSON.stringify(response));
  } catch (error) {
    const response: BridgeFailure = {
      version: 1,
      ok: false,
      error: { code: "MODEL_ERROR", message: errorMessage(error) },
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
