declare module "@earendil-works/pi-coding-agent" {
  export interface ExtensionAPI {
    registerTool(definition: unknown): void;
    exec(
      command: string,
      args: string[],
      options?: { signal?: AbortSignal },
    ): Promise<{ stdout: string; stderr: string; code: number }>;
  }
}
