"""Translate host LangChain content blocks into portable Claude live content."""

from .sdk.dao import ClaudeImageDAO, ClaudeTextDAO


class ClaudeHostContent:
    """Own the lossless text/base64-image block translation at the bridge entry."""

    @classmethod
    def translate(cls, *, block: object) -> ClaudeTextDAO | ClaudeImageDAO:
        """Validate one borrowed LangChain block into portable live content.

        Args:
            block: Heterogeneous vendor input, including empty text.

        Returns:
            A validated text or base64 image DAO.

        Raises:
            ValueError: Unsupported fields, kinds or malformed payloads.
        """
        if isinstance(block, str):
            return ClaudeTextDAO(text=block)
        content: dict[str, object] = cls._content_mapping(value=block)
        if content.get("type") == "text" and set(content) == {"type", "text"}:
            text: object = content["text"]
            if not isinstance(text, str):
                raise ValueError("Unsupported Claude text content.")
            return ClaudeTextDAO(text=text)
        if content.get("type") != "image" or set(content) != {"type", "source"}:
            raise ValueError("Unsupported Claude content block.")
        source: dict[str, object] = cls._content_mapping(value=content["source"])
        media_type: object = source.get("media_type")
        data: object = source.get("data")
        if (
            set(source) != {"type", "media_type", "data"}
            or source["type"] != "base64"
            or not isinstance(media_type, str)
            or not isinstance(data, str)
        ):
            raise ValueError("Unsupported Claude image source.")
        return ClaudeImageDAO.model_validate({"media_type": media_type, "data": data})

    @classmethod
    def model_context(cls, *, content: object) -> str | list[str | dict[str, object]]:
        """Reduce live/replayed content without retaining reasoning in fingerprints.

        Args:
            content: Borrowed LangChain string or ordered block list.

        Returns:
            Joined plain text or ordered mixed blocks with string keys.

        Raises:
            ValueError: Invalid container, block keys or plain-text payload.
        """
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            raise ValueError("Unsupported Claude content list.")
        kept: list[str | dict[str, object]] = []
        texts: list[str] = []
        for block in content:
            if isinstance(block, str):
                kept.append(block)
                texts.append(block)
                continue
            mapping: dict[str, object] = cls._content_mapping(value=block)
            if mapping.get("type") in ("thinking", "reasoning"):
                continue
            if mapping.get("type") == "text" and set(mapping) <= {"type", "text", "index"}:
                text: object = mapping.get("text")
                if not isinstance(text, str):
                    raise ValueError("Unsupported Claude text content.")
                texts.append(text)
            kept.append(mapping)
        return "".join(texts) if len(texts) == len(kept) else kept

    @classmethod
    def translate_all(cls, *, content: object) -> tuple[ClaudeTextDAO | ClaudeImageDAO, ...]:
        """Validate the entire borrowed message before returning ordered blocks.

        Args:
            content: Heterogeneous LangChain content.

        Returns:
            Complete portable content, including empty strings and lists.

        Raises:
            ValueError: Any block or the outer container is unsupported.
        """
        if isinstance(content, str):
            return (cls.translate(block=content),)
        if not isinstance(content, list):
            raise ValueError("Unsupported Claude content list.")
        return tuple(cls.translate(block=block) for block in content)

    @classmethod
    def _content_mapping(cls, *, value: object) -> dict[str, object]:
        """Copy vendor mapping keys after validation, without coercion.

        Args:
            value: Borrowed block or image source.

        Returns:
            A string-keyed shallow copy; nested values remain untrusted.

        Raises:
            ValueError: The value is not a dictionary with only string keys.
        """
        if not isinstance(value, dict):
            raise ValueError("Unsupported Claude content mapping.")
        content: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Unsupported Claude content key.")
            content[key] = item
        return content
