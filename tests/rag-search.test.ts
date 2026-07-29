import assert from "node:assert/strict";
import test from "node:test";

import { parseRecallSearchResponse } from "../agent/extensions/rag-search.ts";

test("parses successful Recall search JSON", () => {
  const results = parseRecallSearchResponse(
    JSON.stringify({
      version: 1,
      ok: true,
      data: { results: [{ document_id: "doc_1", content: "hit" }] },
    }),
  );

  assert.deepEqual(results, [{ document_id: "doc_1", content: "hit" }]);
});

test("rejects failed Recall search JSON", () => {
  assert.throws(
    () =>
      parseRecallSearchResponse(
        JSON.stringify({
          version: 1,
          ok: false,
          error: { code: "STORE_ERROR", message: "broken" },
        }),
      ),
    /STORE_ERROR: broken/,
  );
});
