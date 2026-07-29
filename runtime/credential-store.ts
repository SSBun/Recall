import { randomUUID } from "node:crypto";
import { chmod, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import type {
  Credential,
  CredentialInfo,
  CredentialStore,
} from "@earendil-works/pi-ai";
import { lock } from "proper-lockfile";

type AuthFile = Record<string, Credential>;

export class FileCredentialStore implements CredentialStore {
  private readonly authPath: string;

  constructor(authPath: string) {
    this.authPath = authPath;
  }

  async read(providerId: string): Promise<Credential | undefined> {
    return (await this.readAll())[providerId];
  }

  async list(): Promise<readonly CredentialInfo[]> {
    return Object.entries(await this.readAll()).map(([providerId, credential]) => ({
      providerId,
      type: credential.type,
    }));
  }

  async modify(
    providerId: string,
    update: (current: Credential | undefined) => Promise<Credential | undefined>,
  ): Promise<Credential | undefined> {
    return this.withLock(async () => {
      const credentials = await this.readAll();
      const next = await update(credentials[providerId]);
      if (next === undefined) {
        return credentials[providerId];
      }
      credentials[providerId] = next;
      await this.writeAll(credentials);
      return next;
    });
  }

  async delete(providerId: string): Promise<void> {
    await this.withLock(async () => {
      const credentials = await this.readAll();
      if (credentials[providerId] === undefined) {
        return;
      }
      delete credentials[providerId];
      await this.writeAll(credentials);
    });
  }

  private async withLock<T>(operation: () => Promise<T>): Promise<T> {
    await this.ensureFile();
    const release = await lock(this.authPath, {
      realpath: false,
      stale: 30_000,
      retries: { retries: 10, factor: 2, minTimeout: 50, maxTimeout: 1_000 },
    });
    try {
      return await operation();
    } finally {
      await release();
    }
  }

  private async readAll(): Promise<AuthFile> {
    await this.ensureFile();
    const parsed: unknown = JSON.parse(await readFile(this.authPath, "utf8"));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`认证文件格式错误: ${this.authPath}`);
    }

    const credentials: AuthFile = {};
    for (const [providerId, value] of Object.entries(parsed)) {
      credentials[providerId] = parseCredential(value, this.authPath);
    }
    return credentials;
  }

  private async writeAll(credentials: AuthFile): Promise<void> {
    const temporaryPath = `${this.authPath}.${process.pid}.${randomUUID()}.tmp`;
    try {
      await writeFile(temporaryPath, JSON.stringify(credentials, null, 2), {
        encoding: "utf8",
        mode: 0o600,
      });
      await rename(temporaryPath, this.authPath);
      await chmod(this.authPath, 0o600);
    } finally {
      await rm(temporaryPath, { force: true });
    }
  }

  private async ensureFile(): Promise<void> {
    const directory = dirname(this.authPath);
    await mkdir(directory, { recursive: true, mode: 0o700 });
    await chmod(directory, 0o700);
    try {
      await writeFile(this.authPath, "{}", {
        encoding: "utf8",
        flag: "wx",
        mode: 0o600,
      });
    } catch (error) {
      if (!error || typeof error !== "object" || !("code" in error) || error.code !== "EEXIST") {
        throw error;
      }
    }
    await chmod(this.authPath, 0o600);
  }
}

function parseCredential(value: unknown, authPath: string): Credential {
  if (!value || typeof value !== "object" || !("type" in value)) {
    throw new Error(`认证文件格式错误: ${authPath}`);
  }
  if (
    value.type === "api_key" &&
    "key" in value &&
    typeof value.key === "string" &&
    value.key.length > 0
  ) {
    return { type: "api_key", key: value.key };
  }
  if (
    value.type === "oauth" &&
    "access" in value &&
    typeof value.access === "string" &&
    value.access.length > 0 &&
    "refresh" in value &&
    typeof value.refresh === "string" &&
    value.refresh.length > 0 &&
    "expires" in value &&
    typeof value.expires === "number" &&
    Number.isFinite(value.expires)
  ) {
    return value as Credential;
  }
  throw new Error(`认证文件包含无效凭据: ${authPath}`);
}
