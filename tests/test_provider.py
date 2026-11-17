import ape
import pytest
from ape.exceptions import ProviderError


@pytest.fixture
def rpc_responses(mocker):
    post_mock = mocker.patch("requests.Session.post")

    def set_result(result):
        post_mock.return_value = mocker.Mock(ok=True, json=lambda: {"result": result})

    return set_result


def test_connect_rejects_wrong_genesis_hash(rpc_responses):
    provider = ape.networks.solana.devnet.get_provider("solana")
    rpc_responses("5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d")

    with pytest.raises(ProviderError, match="is not Solana devnet"):
        provider.connect()

    assert not provider.is_connected
