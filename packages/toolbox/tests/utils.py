from contextlib import suppress

from hypothesis import strategies as st


def any_comparables() -> st.SearchStrategy[object]:
    """Generate anything Hypothesis can generate that equals itself."""

    def is_comparable(x: object) -> bool:
        # Suppress all exceptions because some values (such as signaling NaNs:
        # Decimal("sNaN")) throw an exception when compared.
        with suppress(Exception):
            # Disable the self-comparison lint as Hypothesis might be able to generate
            # values other than NaN that don't compare equal to themself.
            return x == x  # noqa: PLR0124
        return False

    return st.from_type(object).filter(is_comparable)
