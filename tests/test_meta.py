# test: allow-vs16
r"""
If you're reading this docstring, it's probably because you added an emoji, ran the
tests, and got yelled at to read this docstring along with some cryptic message about
the number 16 when you really just want to get on with what you were doing. So the
easiest fix is: delete the emoji, use *Discord's emoji picker* to insert the emoji,
**send the message**, then copy paste the emoji character from the message into your
editor. If the test fails again on the same line, add a `# test: allow-vs16` comment to
that line.

And if you want to learn why you were warned about some "VS16" thing, read on.

Unicode has many "Variation Selectors"¹ to control the glyph used to display
a character. Two of those are relevant for emoji: the text variation selector (variation
selector 15, or VS15), and the emoji variation selector (VS16). Here's a quick demo of
what they do:

  - Base character (no variation selector):  👍 (U+1F44D)
  - Emoji with the text variation selector:  👍︎ (U+1F44D U+FE0E)
  - Emoji with the emoji variation selector: 👍️ (U+1F44D U+FE0F)

Assuming the program you're using to read this handles them correctly², the first should
be the standard emoji you know and love, the second should be a monochrome outline of
a thumbs-up, and the last should look identical to the first. We can hence see that
there are two distinct glyphs that can be used for an emoji: a text glyph that matches
the styling of normal text, and the emoji one that is its own distinct pictogram.

Variation selectors are invisible characters that modify the presentation of the
previous character. There's a few at the end of this line, right after the colon:︎️︎️.
If you put the previous line in a hex editor, you'd see something like this at the end:
    00000050: 3aef b88e efb8 8fef b88e efb8 8f2e       :.............
ef b8 8e is the text variation selector, and ef b8 8f is the emoji variation selector,
both encoded in UTF-8. So they definitely do exist! You just can't see them, unless
they're modifying the emoji before it (which doesn't apply in that case, since there is
no emoji).

Here's another example:

  - Base character (no variation selector):  ❤  (U+2764)
  - Emoji with the text variation selector:  ❤︎  (U+2764 U+FE0E)
  - Emoji with the emoji variation selector: ❤️ (U+2764 U+FE0F)

This time, the first and second should look like a filled-in monochrome heart, while the
last one is the emoji glyph. This is an important distinction: the emoji variation
selector isn't always unnecessary³, which is the reason `# test: allow-vs16` was alluded
to in the first paragraph.

Now onto why emoji variation selectors are considered "harmful" by this file. If you
tried pasting the three thumbs-up emojis above into Discord and hit send, you'd notice
that the first and the third one *don't* look the same: the first is converted to an SVG
Twemoji, while the third is displayed with your system emoji font⁴! This is the reason
why this test disallows the VS16 code-point unless you explicitly allow it: to ensure
all emojis that are added are properly handled by Discord.

If you repeat that with the heart emojis above, you'd immediately realize what the
purpose of `# test: allow-vs16` is. Discord handles them *correctly*, displaying the
first as the textual representation and the last as a SVG Twemoji! So if you wanted an
emoji, you'd have to keep the variation selector this test disallows; placing `# test:
allow-vs16` on that line would suppress the warning.

You may now be wondering, how do you remove the VS16 to make the test pass? After all,
they're invisible characters, which is what makes them particularly insidious (when
interacting with Discord) in the first place!

Short answer: don't! Use Discord's emoji picker instead. (See the first paragraph.)

Long answer: you're going to have to find some way to only get the first code-point from
a variation sequence. Here's a non-exhaustive list:
  - Use a hex editor to carefully remove the `ef b8 8f` bytes.
  - Pipe to `sed 's/\xef\xb8\x8f//g'`.
  - Find a broken text editor⁵ that lets you select the variation selector individually.
Or you can find a different emoji picker that doesn't include the VS16 in the first
place. Discord's one, for example.

There is one other case where you may want to ignore the VS16: when you *specifically*
want the emoji to not be converted to an SVG Twemoji, for some reason. In that case,
ignore the VS16, but also add another comment elaborating on why you're ignoring a VS16
that isn't necessary! Do not use a backslash before the emoji: that shows the emoji
without conversion on desktop, and the emoji short-code on mobile.

One note: if you already committed before running the tests, please amend your commit
(git commit --amend) instead of adding a new one! Since variation selectors are
invisible, and the problematic ones are the ones where the default presentation is
*identical* to the emoji presentation, diffs where only that changed look very confusing
(see commit 798365ee17f10f483b112d51d0fce63308c66da5 for an example).


¹The text above only covers the variation selectors used for emoji; see
 https://en.wikipedia.org/wiki/Variation_Selectors_(Unicode_block) and
 https://unicode.org/faq/vs.html for more general information.

²https://faultlore.com/blah/text-hates-you 😁.

³Bonus info: Unicode defines the default presentation for every emoji glyph! You can
 find them in easy-to-parse text files alongside the other emoji data over at
 https://www.unicode.org/reports/tr51/#emoji_data (look for Emoji_Presentation in
 emoji-data.txt). And while we're at it, here's the relevant sections from the emoji
 standard: https://www.unicode.org/reports/tr51/#Emoji_Presentation and
 https://www.unicode.org/reports/tr51/#Emoji_Properties_and_Data_Files.

⁴If Twemoji is also your system emoji font, it's a bit harder to notice, but try
 clicking on them; only the first one would be clickable. Another more subtle difference
 is that the first one is also a little bit larger than the line height.

⁵https://lord.io/text-editing-hates-you-too 🤭.
"""

from pathlib import Path

import pytest

VS16 = "\ufe0f"
VS16_SUPPRESS_COMMENT = "# test: allow-vs16"


def check_dir_for_vs16(path: Path) -> None:
    unsuppressed: list[tuple[Path, int]] = []
    unnecessary: list[tuple[Path, int]] = []
    for file in path.rglob("*.py"):
        if (
            not (lines := file.read_text().splitlines())
            or lines[0] == VS16_SUPPRESS_COMMENT
        ):
            continue
        for line_no, line in enumerate(lines, 1):
            if VS16 in line and VS16_SUPPRESS_COMMENT not in line:
                unsuppressed.append((file, line_no))
            elif VS16_SUPPRESS_COMMENT in line and VS16 not in line:
                unnecessary.append((file, line_no))

    msg = ""
    if unsuppressed:
        n = len(unsuppressed)
        msg += (
            f"unsuppressed VS16 found in {n} line{'s' * (n != 1)}:\n"
            + "\n".join(f"- {file}:{line_no}" for file, line_no in unsuppressed)
            + "\nsee the module docstring of this test for more information"
        )
    if unnecessary:
        n = len(unnecessary)
        msg += (
            f"unnecessary `test: allow-vs16` found in {n} line{'s' * (n != 1)}:\n"
            + "\n".join(f"- {file}:{line_no}" for file, line_no in unnecessary)
        )
    if msg:
        raise AssertionError(msg)


@pytest.mark.parametrize("folder", ["app", "tests"])
def test_self_unwanted_vs16(folder: str) -> None:
    root = Path(__file__).parents[1]
    check_dir_for_vs16(root / folder)


def test_dummy_unwanted_vs16(tmp_path: Path) -> None:
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "bar.py").write_text(VS16)
    (tmp_path / "foo" / "baz.py").write_text("\u2764" + VS16)

    (tmp_path / "qux").mkdir()
    (tmp_path / "qux" / "foo.py").write_text("\u2764\ufffd")
    (tmp_path / "qux" / "bar.txt").write_text(VS16)

    check_dir_for_vs16(tmp_path / "qux")

    with pytest.raises(AssertionError, match="found in 2 lines"):
        check_dir_for_vs16(tmp_path / "foo")
