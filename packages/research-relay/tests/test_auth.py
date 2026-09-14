from research_relay.auth import AppPasswordAuth, OAuth2Auth, build_auth


class DummyImap:
    def __init__(self) -> None:
        self.logged_in = None
        self.auth = None

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def authenticate(self, mechanism: str, callback) -> None:
        self.auth = (mechanism, callback(b""))


def test_app_password_auth_logs_in() -> None:
    auth = AppPasswordAuth("user@gmail.com", "app-pass")
    imap = DummyImap()
    auth.authenticate_imap(imap)
    assert imap.logged_in == ("user@gmail.com", "app-pass")


def test_factory_selects_app_password() -> None:
    auth = build_auth("app_password", username="u", password="p")
    assert isinstance(auth, AppPasswordAuth)


def test_factory_selects_oauth() -> None:
    auth = build_auth("oauth2", username="u@gmail.com", access_token="tok")
    assert isinstance(auth, OAuth2Auth)
