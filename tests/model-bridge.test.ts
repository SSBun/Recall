import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  createModels,
  fauxAssistantMessage,
  fauxProvider,
  fauxText,
} from "@earendil-works/pi-ai";

import {
  completeWithModels,
  listAvailableModelReferences,
  parseModelReference,
} from "../runtime/model-bridge.ts";
import { FileCredentialStore } from "../runtime/credential-store.ts";

test("bridge resolves provider/model and returns faux provider text", async () => {
  const faux = fauxProvider({ provider: "recall-test" });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([fauxAssistantMessage([fauxText("bridge answer")])]);

  const result = await completeWithModels(
    {
      version: 1,
      prompt: "question",
      model: `recall-test/${faux.getModel().id}`,
    },
    models,
  );

  assert.equal(result.text, "bridge answer");
  assert.equal(faux.state.callCount, 1);
});

test("lists every model available from configured providers", async () => {
  const models = createModels();
  models.setProvider(
    fauxProvider({
      provider: "recall-zeta",
      models: [{ id: "model-b" }, { id: "model-a" }],
    }).provider,
  );
  models.setProvider(
    fauxProvider({
      provider: "recall-alpha",
      models: [{ id: "model-c" }],
    }).provider,
  );

  assert.deepEqual(await listAvailableModelReferences(models), [
    "recall-alpha/model-c",
    "recall-zeta/model-a",
    "recall-zeta/model-b",
  ]);
});

test("model references preserve slashes inside model ids", () => {
  assert.deepEqual(parseModelReference("openrouter/vendor/model"), [
    "openrouter",
    "vendor/model",
  ]);
  assert.throws(() => parseModelReference("missing-provider"), /provider\/model/);
});

test("OAuth login and refresh persist in the Recall credential store", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "recall-auth-"));
  t.after(() => rm(directory, { recursive: true }));
  const authPath = join(directory, "auth.json");
  const credentials = new FileCredentialStore(authPath);
  const faux = fauxProvider({ provider: "oauth-test" });
  const models = createModels({ credentials });
  models.setProvider({
    ...faux.provider,
    auth: {
      oauth: {
        name: "Test OAuth",
        login: async () => ({
          type: "oauth",
          access: "old-access",
          refresh: "old-refresh",
          expires: 0,
        }),
        refresh: async () => ({
          type: "oauth",
          access: "new-access",
          refresh: "new-refresh",
          expires: Date.now() + 60_000,
        }),
        toAuth: async (credential) => ({ apiKey: credential.access }),
      },
    },
  });

  await models.login("oauth-test", "oauth", {
    prompt: async () => "",
    notify: () => undefined,
  });
  const auth = await models.getAuth("oauth-test");

  assert.equal(auth?.auth.apiKey, "new-access");
  assert.equal(
    (await new FileCredentialStore(authPath).read("oauth-test"))?.type,
    "oauth",
  );
  assert.deepEqual(await credentials.list(), [
    { providerId: "oauth-test", type: "oauth" },
  ]);
  assert.match(await readFile(authPath, "utf8"), /new-refresh/);
  assert.equal((await stat(authPath)).mode & 0o777, 0o600);
  assert.equal((await stat(directory)).mode & 0o777, 0o700);

  await models.logout("oauth-test");
  assert.equal(await credentials.read("oauth-test"), undefined);
});

test("concurrent credential updates preserve both providers", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "recall-auth-lock-"));
  t.after(() => rm(directory, { recursive: true }));
  const authPath = join(directory, "auth.json");
  const first = new FileCredentialStore(authPath);
  const second = new FileCredentialStore(authPath);

  await Promise.all([
    first.modify("openai", async () => ({ type: "api_key", key: "one" })),
    second.modify("anthropic", async () => ({ type: "api_key", key: "two" })),
  ]);

  assert.deepEqual(
    new Set((await first.list()).map((credential) => credential.providerId)),
    new Set(["openai", "anthropic"]),
  );
});

test("provider failures reject instead of returning an empty answer", async () => {
  const faux = fauxProvider({ provider: "recall-empty" });
  const models = createModels();
  models.setProvider(faux.provider);

  await assert.rejects(
    completeWithModels(
      {
        version: 1,
        prompt: "question",
        model: `recall-empty/${faux.getModel().id}`,
      },
      models,
    ),
    /No more faux responses queued/,
  );
});
