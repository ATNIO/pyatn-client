import os
import json
from web3 import Web3

from ..constants import CONTRACT_METADATA, CHANNEL_MANAGER_NAME
from ..utils import privkey_to_addr


class Context(object):
    def __init__(
            self,
            private_key: str,
            web3: Web3,
            channel_manager_address: str
    ):
        self.private_key = private_key
        self.address = privkey_to_addr(private_key)
        self.web3 = web3
        self.account = web3.eth.account.privateKeyToAccount(private_key)

        self.channel_manager = web3.eth.contract(
            address=channel_manager_address,
            abi=CONTRACT_METADATA[CHANNEL_MANAGER_NAME]['abi']
        )
