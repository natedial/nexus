from research_relay.htmltext import html_to_text


def test_converts_simple_html_without_tags() -> None:
    html = "<html><body><p>Hello <b>world</b>.</p></body></html>"
    text = html_to_text(html)
    assert "Hello world." in text
    assert "<p>" not in text


def test_does_not_include_script_or_style() -> None:
    html = "<style>body{color:red}</style><script>alert(1)</script><p>Safe</p>"
    text = html_to_text(html)
    assert "Safe" in text
    assert "alert" not in text
    assert "color:red" not in text


def test_does_not_fetch_or_embed_remote_images() -> None:
    html = '<p>Hi</p><img src="https://tracker.example/pixel.gif" alt="x">'
    text = html_to_text(html)
    assert "https://tracker.example/pixel.gif" not in text
    assert "Hi" in text


def test_uses_link_text_without_fetching() -> None:
    html = '<p>See <a href="https://example.edu/job">the posting</a>.</p>'
    text = html_to_text(html)
    assert "the posting" in text
    assert "alert" not in text


def test_malformed_html_does_not_raise() -> None:
    text = html_to_text("<p>Unclosed <div><b>broken")
    assert "Unclosed" in text
    assert "broken" in text
