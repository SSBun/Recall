import cmd2

PROVIDER_OPTIONS = [
    ("openai-codex", "OpenAI Codex（ChatGPT Plus/Pro OAuth）"),
]


def select_provider() -> str:
    return cmd2.Cmd(allow_cli_args=False).select(
        PROVIDER_OPTIONS,
        prompt="选择要登录的供应商：",
    )
