#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import logging
import logging.config
import time
from typing import Callable, Tuple, Union
import json
from munch import Munch
import requests
from requests import Response

from web3 import Web3, HTTPProvider
from web3.middleware import geth_poa_middleware
from eth_utils import is_same_address, decode_hex, encode_hex

from .microraiden.header import HTTPHeaders
from .microraiden.client import Client, Channel
from .microraiden.utils import verify_balance_proof

from .utils import remove_slash_prefix, tobytes32
from .log import AtnLogger

logger = logging.getLogger('atn')

class AtnException(Exception):
    """Base exception for ATN Client"""
    pass

def _make_dbot_contract(web3, dbot_address):
    contracts_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contracts.json')
    if os.path.exists(contracts_file):
        with open(contracts_file) as fh:
            contracts = json.load(fh)
    else:
        contracts = json.loads(pkg_resources.resource_string('pyatn_client', 'contracts.json'))
    dbot_address = Web3.toChecksumAddress(dbot_address)
    dbotContract = web3.eth.contract(address=dbot_address,
                                     abi=contracts['Dbot']['abi'],
                                     bytecode=contracts['Dbot']['bytecode'])
    return dbotContract

class Atn():
    """ATN Client Class

    Usage::

      >>> from pyatn_client import Atn
      >>> atn = Atn(pk_file='<path to keystore file>',
      >>>           pw_file='<path to password file>'
      >>> )
      >>> resp = atn.call_dbot_api(dbot_address='0xfd4F504F373f0af5Ff36D9fbe1050E6300699230',
      >>>                          uri='/reg',
      >>>                          method='POST',
      >>>                          data={'theme': '中秋月更圆'})
      <Response [200]>
    """
    def __init__(
        self,
        pk_file: str,
        pw_file: str,
        http_provider: str = 'https://rpc-test.atnio.net',
        deposit_strategy: Callable[[int], int] = lambda value: 10 * value
    ) -> None:
        """Init Atn Class

        """
        logging.config.dictConfig(AtnLogger('atn').config())

        w3 = Web3(HTTPProvider(http_provider))
        w3.middleware_stack.inject(geth_poa_middleware, layer=0)

        self.deposit_strategy = deposit_strategy
        self.channel_client = Client(
            private_key=pk_file,
            key_password_path=pw_file,
            web3=w3
        )

    def set_deposit_strategy(self, deposit_strategy: Callable[[int], int]) -> None:
        """Change deposit strategy.

        Channel will be auto created if no channel or be topuped if
        insufficient balance in channel when `call_dbot_api` be called.
        The deposit value is determined by `deposit_strategy`.

        :param deposit_strategy: callable function to determine the deposit
            value when create and topup channel.
            If it's `None`, disable auto create or topup channel
        """
        self.deposit_strategy = deposit_strategy

    def get_dbot_name(self, dbot_address: str) -> str:
        """Get the name of DBot according the address of DBot contract
        on ATN blockchain.

        :param dbot_address: address of the DBot contract
        :return: name of the DBot
        :rtype: str
        """
        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        name = Dbot.functions.name().call()
        return name.decode('utf-8').rstrip('\0')

    def get_dbot_domain(self, dbot_address: str) -> str:
        """Get the domain of DBot according the address of DBot contract
        on ATN blockchain.

        The DBot server should be accessed on the domain.
        The domain may contain `http://` or `https://` protocol prefix.

        :param dbot_address: address of the DBot contract
        :return: domain of the DBot
        :rtype: str
        """
        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        domain = Dbot.functions.domain().call()
        return domain.decode('utf-8').rstrip('\0')

    def get_dbot_owner(self, dbot_address: str) -> str:
        """Get the owner account of DBot contract on ATN blockchain.

        Close signature should be signed by the owner of DBot
        when DBot user want to cooperative close the channel with DBot.

        :param dbot_address: address of the DBot contract
        :return: account address of owner
        :rtype: str
        """
        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        owner = Dbot.functions.getOwner().call()
        return owner

    def get_price(self, dbot_address: str, uri: str, method: str) -> int:
        """Get the price of a endpoint of the DBot

        The unit of price is `wei`, the smallest unit of ATN. 1ATN = 10^18wei

        :param dbot_address: address of the DBot contract
        :param uri: uri of the endpoint
        :param method: method of the endpoint
        :return: price of the DBot's endpoint
        :rtype: int
        """

        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        key = Dbot.functions.getKey(tobytes32(method.lower()), tobytes32(uri)).call()
        endpoint = Dbot.functions.keyToEndPoints(key).call()
        # TODO handle method case and how to check if the endpoint exist
        if (int(endpoint[1]) == 0):
            raise AtnException('no such endpoint: uri = {}, method = {}'.format(uri, method))
        else:
            return int(endpoint[1])

    def get_dbot_channel(self, dbot_address: str) -> Channel:
        """Get the channel information from DBot server

        DBot server saves the balance proof which send from DBot user.
        DBot users can get this from DBot server, no need to save by themselves.

        :param dbot_address: address of the DBot contract
        :return: :class:`Channel <Channel>` object
        :rtype: pyatn_client.Channel
        """
        dbot_address = Web3.toChecksumAddress(dbot_address)
        domain = self.get_dbot_domain(dbot_address)
        channel = self.get_channel(dbot_address)
        dbot_url = domain if domain.lower().startswith('http') else 'http://{}'.format(domain)
        if channel is not None:
            url = '{}/api/v1/dbots/{}/channels/{}/{}'.format(dbot_url,
                                                             channel.receiver,
                                                             channel.sender,
                                                             channel.block
                                                             )
            resp = requests.get(url)
            if resp.status_code == 200:
                return resp.json()
            else:
                return None
        else:
            return None

    def wait_dbot_sync(self, dbot_address: str, retry_interval: int=5, retry_times: int=5) -> None:
        """Wait the DBot server to sync the channel info on blockchain

        DBot server will sync the channel info on blockchain, and

        :param dbot_address: address of the DBot contract
        :param retry_interval: interval time for retry, seconds
        :param retry_times:  how many times to retry
        """
        dbot_address = Web3.toChecksumAddress(dbot_address)
        channel = self.get_channel(dbot_address)
        if channel is None:
            logger.warning('No Channel with dbot({}) on chain'.format(dbot_address))
            return
        dbot_channel = self.get_dbot_channel(dbot_address)
        remain_times = retry_times
        while retry_times > 0 and (dbot_channel is None or int(dbot_channel['deposit']) != channel.deposit):
            logger.info('Channel state with dbot({}) has not synced by dbot server, retry after {}s'.format(
                dbot_address, retry_interval))
            remain_times = remain_times - 1
            time.sleep(retry_interval)
            dbot_channel = self.get_dbot_channel(dbot_address)
        if dbot_channel is not None and int(dbot_channel['deposit']) == channel.deposit:
            channel.update_balance(int(dbot_channel['balance']))
        else:
            raise AtnException('Channel state with dbot({}) can not synced by dbot server.'.format(dbot_address))

    def call_dbot_api(self, dbot_address: str, uri: str, method: str, **requests_kwargs) -> Response:
        """Send the API's HTTP request

        Channel will be auto created if no channel or be topuped if
        insufficient balance in channel.
        The deposit value is determined by `deposit_strategy`.
        A signature of balance will be sent to DBot server to pay the price of the API.

        :param dbot_address: address of the DBot contract
        :param uri: uri of the endpoint
        :param method: method of the endpoint
        :param requests_kwargs: the other args for http request is same with `requests`
        :return: :class:`Response <Response>` object, http response of the API
        :rtype: requests.Response
        """
        dbot_address = Web3.toChecksumAddress(dbot_address)
        price = self.get_price(dbot_address, uri, method)
        channel = self._get_suitable_channel(dbot_address, price)
        channel.create_transfer(price)
        domain = self.get_dbot_domain(dbot_address)
        dbot_url = domain if domain.lower().startswith('http') else 'http://{}'.format(domain)
        url = '{}/call/{}/{}'.format(dbot_url, dbot_address, remove_slash_prefix(uri))
        return self._request(channel, method, url, **requests_kwargs)

    def open_channel(self, dbot_address: str, deposit: int) -> Channel:
        """Open a channel with the DBot

        If a channel with the DBot has exist, the channel will be return directlly.
        This function will block until the `ChannelCreated` event received
        from blockchain.

        :param dbot_address: address of the DBot contract
        :param deposit: the value of deposit
        :return: :class:`Channel <Channel>` object, None if failed.
        :rtype: Channel
        """
        channel = self.get_channel(dbot_address)
        if channel is not None:
            logger.warning('A channel is exist')
            return channel
        return self.channel_client.open_channel(dbot_address, deposit)

    def topup_channel(self, dbot_address: str, deposit: int) -> Channel:
        """Topup the channel with the DBot

        This function will block until the `ChannelToppedUp` event received
        from blockchain.

        :param dbot_address: address of the DBot contract
        :param deposit: the value of deposit
        :return: :class:`Channel <Channel>` object, `None` if failed.
        :rtype: Channel
        """
        return self.channel_client.topup_channel(dbot_address, deposit)

    def close_channel(self, dbot_address: str) -> None:
        """Close the channel with the DBot

        This function will block until the `ChannelSettled` event received
        from blockchain.
        If can not get valid close signature from DBot server,
        it will close the channel with balance 0 unilaterally.
        You can change the manual through redefine `on_cooperative_close_denied`

        :param dbot_address: address of the DBot contract
        """
        channel = self.get_channel(dbot_address)
        if channel is None:
            logger.error('No channel to close.')
            return

        try:
            self.wait_dbot_sync(dbot_address)
        except Exception as err:
            logger.error('Dbot server can not sync the channel')
            self.on_cooperative_close_denied(dbot_address, response)
        domain = self.get_dbot_domain(dbot_address)
        dbot_url = domain if domain.lower().startswith('http') else 'http://{}'.format(domain)

        logger.debug(
            'Requesting closing signature from server for balance {} on channel {}/{}/{}.'
            .format(
                channel.balance,
                channel.receiver,
                channel.sender,
                channel.block
            )
        )
        url = '{}/api/v1/channels/{}/{}/{}'.format(
            dbot_url,
            channel.receiver,
            channel.sender,
            channel.block
        )

        try:
            response = requests.request(
                'DELETE',
                url,
                params={'balance': channel.balance}
            )
        except requests.exceptions.ConnectionError as err:
            logger.error(
                'Could not get a response from the server while requesting a closing signature: {}'
                .format(err)
            )
            response = None

        failed = True
        if response is not None and response.status_code == requests.codes.OK:
            closing_sig = response.json()['close_signature']
            dbot_owner = self.get_dbot_owner(dbot_address)
            failed = channel.close_cooperatively(decode_hex(closing_sig), dbot_owner) is None

        if response is None or failed:
            logger.error('Cooperative close channel failed.')
            self.on_cooperative_close_denied(dbot_address, response)
        else:
            logger.info('Cooperative close channel successfully')

    def on_cooperative_close_denied(self, dbot_address: str, response: Response = None) -> None:
        """Call back function when no valid closing signature received

        This function will be called when can not get valid closing signature in
        method `close_channel`

        :param dbot_address: address of the DBot contract
        :param response: response from DBot server when request closing signature
        """
        logger.warning('No valid closing signature received from DBot server({}).\n{}'.format(dbot_address, response.text))
        logger.warning('Closing noncooperatively on a balance of 0.')
        # if cooperative close denied, client close the channel with balance 0 unilaterally
        self.uncooperative_close_channel(dbot_address, 0)

    def uncooperative_close_channel(self, dbot_address: str, balance: int) -> None:
        """Close the channel unilaterally

        If DBot server has down, you can close the channel with any balance.
        DBot server will close the channel if it's working and detect that
        you send a wrong balance.

        :param dbot_address: address of the DBot contract
        :param balance: used balance of the channel
        """
        channel = self.get_channel(dbot_address)
        if channel is None:
            logger.error('No channel to close.')
            return
        channel.close(balance)

    def settle_channel(self, dbot_address: str) -> None:
        """Settle the channel to withdraw your deposit after you close the channel unilaterally

        This function should be called after the end of the challenge peroid

        :param dbot_address: address of the DBot contract
        """
        channel = self.get_channel(dbot_address)
        if channel is None:
            logger.error('No channel to settle.')
            return
        channel.settle()

    def get_channel(self, dbot_address: str) -> Channel:
        """Get channel information from blockchain

        :param dbot_address: address of the DBot contract
        :return: :class:`Channel <Channel>` object, `None` is no channel
        :rtype: Channel
        """
        open_channels = self.channel_client.get_channels(dbot_address)
        if open_channels:
            channel = open_channels[0]
            return channel
        else:
            return None

    def _get_suitable_channel(self,
                             dbot_address: str,
                             price: int
                             ) -> Channel:
        if self.deposit_strategy is None:
            channel = self.get_channel(dbot_address)
            if channel is None:
                logger.error('No channel was found with DBot({}), please create a channel first'.format(dbot_address))
                raise AtnException('No channel was found with DBot({})'.format(dbot_address))
            if not channel.is_suitable(price):
                logger.error('Insufficient balance in the channel (remain balance = {}), please topup first'.format(
                    channel.remain_balance()))
                raise AtnException('Insufficient balance in the channel (remain balance = {}), please topup first'.format(
                    channel.remain_balance()))
            return channel
        else:
            channel = self.channel_client.get_suitable_channel(
                dbot_address, price, self.deposit_strategy, self.deposit_strategy
            )
            if channel is None:
                logger.error("No channel could be created or sufficiently topped up.")
                raise AtnException('No channel could be created or sufficiently topped up.')

            self.wait_dbot_sync(dbot_address)
            if channel.remain_balance() < price:
                channel.topup(self.deposit_strategy(price))
                self.wait_dbot_sync(dbot_address)
            return channel

    def _request(
            self,
            channel: Channel,
            method: str,
            url: str,
            **requests_kwargs
    ) -> Tuple[Union[None, Response], bool]:
        """
        Performs a simple request to the HTTP server with headers representing the given
        channel state.
        """
        headers = Munch()
        headers.contract_address = self.channel_client.context.channel_manager.address
        if channel is not None:
            headers.balance = str(channel.balance)
            headers.balance_signature = encode_hex(channel.balance_sig)
            headers.sender_address = channel.sender
            headers.receiver_address = channel.receiver
            headers.open_block = str(channel.block)

        headers = HTTPHeaders.serialize(headers)
        if 'headers' in requests_kwargs:
            headers.update(requests_kwargs['headers'])
            requests_kwargs['headers'] = headers
        else:
            requests_kwargs['headers'] = headers
        return requests.request(method, url, **requests_kwargs)
