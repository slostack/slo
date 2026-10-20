"""Shared Pi-compatible token display arithmetic without UI dependencies."""


class CompactTokenFormatter:
    """Render integer token quantities with exact half-up rounding."""

    @staticmethod
    def format(*, count: int) -> str:
        """Format a non-negative token count using Pi's compact footer convention.

        WHAT: Selects the Pi-compatible decimal, ``k``, or ``M`` display form.
        WHO: Usage, cache, and token-limit render helpers call it.
        WHEN: A usage snapshot is projected for the status bar or Herdr metadata.

        Args:
            count (int): Non-negative token quantity supplied by the caller;
                this arithmetic helper does not validate or clamp input.

        Returns:
            str: Compact token quantity with Pi-compatible half-up rounding.
        """
        if count < 1_000:
            return str(count)
        if count < 10_000:
            return CompactTokenFormatter._format_one_decimal(
                count=count,
                unit=1_000,
                suffix="k",
            )
        if count < 1_000_000:
            return f"{(count + 500) // 1_000}k"
        if count < 10_000_000:
            return CompactTokenFormatter._format_one_decimal(
                count=count,
                unit=1_000_000,
                suffix="M",
            )
        return f"{(count + 500_000) // 1_000_000}M"

    @staticmethod
    def _format_one_decimal(*, count: int, unit: int, suffix: str) -> str:
        """Format one token magnitude with one decimal place and half-up rounding.

        WHAT: Converts an integer token count into an exact one-decimal compact unit.
        WHO: ``CompactTokenFormatter.format`` calls it for the decimal ``k`` and ``M`` bands.
        WHEN: The selected Pi display band retains one decimal place.

        Args:
            count (int): Token quantity to render.
            unit (int): Whole-unit token divisor.
            suffix (str): Compact-unit suffix.

        Returns:
            str: Half-up rounded compact token quantity.
        """
        scaled_tenths: int = (count + unit // 20) // (unit // 10)
        return f"{scaled_tenths // 10}.{scaled_tenths % 10}{suffix}"
