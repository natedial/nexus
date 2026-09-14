from research_relay.subject import clean_subject


def test_strips_single_re_prefix() -> None:
    assert clean_subject("Re: Interview availability") == "Interview availability"


def test_strips_nested_reply_and_forward_prefixes() -> None:
    assert clean_subject("Re: Fw: Fwd: RE: Campus visit") == "Campus visit"


def test_strips_prefixes_case_insensitively_with_spacing() -> None:
    assert clean_subject("re:  fwd:  Topic") == "Topic"


def test_does_not_strip_re_in_the_middle() -> None:
    assert clean_subject("Talk about Re: the paper") == "Talk about Re: the paper"


def test_handles_empty_and_prefix_only() -> None:
    assert clean_subject("") == ""
    assert clean_subject("Re:") == ""
    assert clean_subject("Fwd: ") == ""
