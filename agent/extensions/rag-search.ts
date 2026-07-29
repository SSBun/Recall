import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type RecallEnvelope = {
	version?: unknown;
	ok?: unknown;
	data?: { results?: unknown };
	error?: { code?: unknown; message?: unknown };
};

export function parseRecallSearchResponse(output: string): unknown[] {
	let envelope: RecallEnvelope;
	try {
		envelope = JSON.parse(output) as RecallEnvelope;
	} catch {
		throw new Error("Recall returned invalid JSON");
	}

	if (envelope.version !== 1) {
		throw new Error("Recall returned an unsupported API version");
	}
	if (envelope.ok !== true) {
		const code = typeof envelope.error?.code === "string" ? envelope.error.code : "RECALL_ERROR";
		const message =
			typeof envelope.error?.message === "string" ? envelope.error.message : "Recall search failed";
		throw new Error(`${code}: ${message}`);
	}
	if (!Array.isArray(envelope.data?.results)) {
		throw new Error("Recall response is missing data.results");
	}
	return envelope.data.results;
}

export default function recallRagSearch(pi: ExtensionAPI) {
	pi.registerTool({
		name: "recall_search",
		label: "Recall Search",
		description: "Search the local Recall knowledge base and return relevant document chunks",
		promptSnippet: "Search the local Recall knowledge base",
		promptGuidelines: [
			"Use recall_search when the user asks for information that may exist in their Recall knowledge base.",
		],
		parameters: Type.Object({
			query: Type.String({ description: "Semantic search query" }),
			limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
			category: Type.Optional(Type.String()),
			tag: Type.Optional(Type.String()),
		}),
		async execute(
			_toolCallId: string,
			params: { query: string; limit?: number; category?: string; tag?: string },
			signal?: AbortSignal,
		) {
			const args = ["search", params.query, "--limit", String(params.limit ?? 5), "--json"];
			if (params.category) args.push("--category", params.category);
			if (params.tag) args.push("--tag", params.tag);

			const result = await pi.exec("recall", args, { signal });
			let results: unknown[];
			try {
				results = parseRecallSearchResponse(result.stdout);
			} catch (error) {
				const fallback = result.stderr.trim();
				if (fallback && !(error instanceof Error && error.message.includes(":"))) {
					throw new Error(fallback);
				}
				throw error;
			}
			if (result.code !== 0) {
				throw new Error(result.stderr.trim() || `Recall exited with code ${result.code}`);
			}

			return {
				content: [{ type: "text", text: JSON.stringify(results, null, 2) }],
				details: { results },
			};
		},
	});
}
