from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def get_tokenizer(encoding: str = "o200k_base") -> tiktoken.Encoding:
    return tiktoken.get_encoding(encoding)


def pre_append_line_numbers(text: str, start_line: int) -> str:
    return "\n".join([f"{start_line + i}. {line}" for i, line in enumerate(text.splitlines())])


TRUNCATED_TEXT = "... Output has been truncated becuase it is too long, please narrow down your query if you wish to see more"
TRUNCATED_TEXT_LEN = len(get_tokenizer().encode(TRUNCATED_TEXT))


def truncate_text(text: str, max_token: int) -> str:
    encoder = get_tokenizer()
    tokens = encoder.encode(text)
    if len(tokens) <= max_token:
        return text

    truncated_tokens = tokens[: max_token - TRUNCATED_TEXT_LEN]
    truncated_text = encoder.decode(truncated_tokens)
    return truncated_text + TRUNCATED_TEXT
