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
    """Base exception for Database"""
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
    def __init__(
        self,
        http_provider: str,
        pk_file: str,
        pw_file: str,
        deposit_strategy: Callable[[int], int] = lambda value: 10 * value,
        debug: bool = False
    ) -> None:
        logging.config.dictConfig(AtnLogger('atn', debug).config())

        w3 = Web3(HTTPProvider(http_provider))
        w3.middleware_stack.inject(geth_poa_middleware, layer=0)

        self.deposit_strategy = deposit_strategy
        self.channel_client = Client(
            private_key=pk_file,
            key_password_path=pw_file,
            web3=w3
        )

    def set_deposit_strategy(self, deposit_strategy: Callable[[int], int]):
        self.deposit_strategy = deposit_strategy

    def get_dbot_name(self, dbot_address: str):
        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        name = Dbot.functions.name().call()
        return name.decode('utf-8').rstrip('\0')

    def get_dbot_domain(self, dbot_address: str):
        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        domain = Dbot.functions.domain().call()
        return domain.decode('utf-8').rstrip('\0')

    def get_dbot_owner(self, dbot_address: str):
        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        owner = Dbot.functions.getOwner().call()
        return owner

    def get_price(self, dbot_address: str, uri: str, method: str):
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

    def get_dbot_channel(self, dbot_address: str):
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

    def wait_dbot_sync(self, dbot_address: str, retry_interval: int=5, retry_times: int=5):
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

    def get_suitable_channel(self,
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

    def call_dbot_api(self, dbot_address: str, uri: str, method: str, **requests_kwargs) -> Response:
        dbot_address = Web3.toChecksumAddress(dbot_address)
        price = self.get_price(dbot_address, uri, method)
        channel = self.get_suitable_channel(dbot_address, price)
        channel.create_transfer(price)
        domain = self.get_dbot_domain(dbot_address)
        dbot_url = domain if domain.lower().startswith('http') else 'http://{}'.format(domain)
        url = '{}/call/{}/{}'.format(dbot_url, dbot_address, remove_slash_prefix(uri))
        return self._request(channel, method, url, **requests_kwargs)

    def open_channel(self, dbot_address: str, deposit: int):
        channel = self.get_channel(dbot_address)
        if channel is not None:
            logger.warning('A channel is exist')
            return channel
        return self.channel_client.open_channel(dbot_address, deposit)

    def topup_channel(self, dbot_address: str, deposit: int):
        return self.channel_client.topup_channel(dbot_address, deposit)

    def close_channel(self, dbot_address: str):
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

    def on_cooperative_close_denied(self, dbot_address: str, response: Response = None):
        logger.warning('No valid closing signature received from DBot server({}).\n{}'.format(dbot_address, response.text))
        logger.warning('Closing noncooperatively on a balance of 0.')
        # if cooperative close denied, client close the dbot with balance 0 unilaterally
        self.uncooperative_close(dbot_address, 0)

    def uncooperative_close(self, dbot_address: str, balance: int):
        channel = self.get_channel(dbot_address)
        if channel is None:
            logger.error('No channel to close.')
            return
        channel.close(balance)

    def settle_channel(self, dbot_address: str):
        channel = self.get_channel(dbot_address)
        if channel is None:
            logger.error('No channel to settle.')
            return
        channel.settle()

    def get_channel(self, dbot_address: str):
        open_channels = self.channel_client.get_channels(dbot_address)
        if open_channels:
            channel = open_channels[0]
            return channel
        else:
            return None

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
    #
    #
    #      if self.on_http_response(method, url, response, **requests_kwargs) is False:
    #          return response, False  # user requested abort
    #
    #      if response.status_code == requests.codes.OK:
    #          return response, self.on_success(method, url, response, **requests_kwargs)
    #
    #      elif response.status_code == requests.codes.PAYMENT_REQUIRED:
    #          if HTTPHeaders.NONEXISTING_CHANNEL in response.headers:
    #              return response, self.on_nonexisting_channel(method, url, response, **requests_kwargs)
    #
    #          elif HTTPHeaders.INSUF_CONFS in response.headers:
    #              return response, self.on_insufficient_confirmations(
    #                  method,
    #                  url,
    #                  response,
    #                  **requests_kwargs
    #              )
    #
    #          elif HTTPHeaders.INVALID_PROOF in response.headers:
    #              return response, self.on_invalid_balance_proof(method, url, response, **requests_kwargs)
    #
    #          elif HTTPHeaders.CONTRACT_ADDRESS not in response.headers or not is_same_address(
    #              response.headers.get(HTTPHeaders.CONTRACT_ADDRESS),
    #              self.channel_client.context.channel_manager.address
    #          ):
    #              return response, self.on_invalid_contract_address(method, url, response, **requests_kwargs)
    #
    #          elif HTTPHeaders.INVALID_AMOUNT in response.headers:
    #              return response, self.on_invalid_amount(method, url, response, **requests_kwargs)
    #
    #          else:
    #              return response, self.on_payment_requested(method, url, response, **requests_kwargs)
    #      else:
    #          return response, self.on_http_error(method, url, response, **requests_kwargs)
    #
    #  def on_nonexisting_channel(
    #          self,
    #          method: str,
    #          url: str,
    #          response: Response,
    #          **requests_kwargs
    #  ) -> bool:
    #      logger.warning('No Channel registered by DBot server')
    #      return True
    #
    #  def on_insufficient_confirmations(
    #          self,
    #          method: str,
    #          url: str,
    #          response: Response,
    #          **requests_kwargs
    #  ) -> bool:
    #      logger.warning('Newly created channel does not have enough confirmations yet.')
    #      time.sleep(self.retry_interval)
    #      return True
    #
    #  def on_invalid_balance_proof(
    #      self,
    #      method: str,
    #      url: str,
    #      response: Response,
    #      **requests_kwargs
    #  ) -> bool:
    #      logger.warning(
    #          'Server was unable to verify the transfer - '
    #          'Either the balance was greater than deposit'
    #          'or the balance proof contained a lower balance than expected'
    #          'or possibly an unconfirmed or unregistered topup.'
    #      )
    #      return True
    #
    #  def on_invalid_amount(
    #          self,
    #          method: str,
    #          url: str,
    #          response: Response,
    #          **requests_kwargs
    #  ) -> bool:
    #      logger.debug('Server claims an invalid amount sent.')
    #      balance_sig = response.headers.get(HTTPHeaders.BALANCE_SIGNATURE)
    #      if balance_sig:
    #          balance_sig = decode_hex(balance_sig)
    #      last_balance = int(response.headers.get(HTTPHeaders.SENDER_BALANCE))
    #
    #      verified = balance_sig and is_same_address(
    #          verify_balance_proof(
    #              self.channel.receiver,
    #              self.channel.block,
    #              last_balance,
    #              balance_sig,
    #              self.channel_client.context.channel_manager.address
    #          ),
    #          self.channel.sender
    #      )
    #
    #      if verified:
    #          if last_balance == self.channel.balance:
    #              logger.error(
    #                  'Server tried to disguise the last unconfirmed payment as a confirmed payment.'
    #              )
    #              return False
    #          else:
    #              logger.debug(
    #                  'Server provided proof for a different channel balance ({}). Adopting.'.format(
    #                      last_balance
    #                  )
    #              )
    #              self.channel.update_balance(last_balance)
    #      else:
    #          logger.debug(
    #              'Server did not provide proof for a different channel balance. Reverting to 0.'
    #          )
    #          self.channel.update_balance(0)
    #
    #      return self.on_payment_requested(method, url, response, **requests_kwargs)
    #
    #  def on_payment_requested(
    #          self,
    #          method: str,
    #          url: str,
    #          response: Response,
    #          **requests_kwargs
    #  ) -> bool:
    #      receiver = response.headers[HTTPHeaders.RECEIVER_ADDRESS]
    #      if receiver and Web3.isAddress(receiver):
    #          receiver = Web3.toChecksumAddress(receiver)
    #      price = int(response.headers[HTTPHeaders.PRICE])
    #      assert price > 0
    #
    #      logger.debug('Preparing payment of price {} to {}.'.format(price, receiver))
    #
    #      if self.channel is None or self.channel.state != Channel.State.open:
    #          new_channel = self.channel_client.get_suitable_channel(
    #              receiver, price, self.initial_deposit, self.topup_deposit
    #          )
    #
    #          if self.channel is not None and new_channel != self.channel:
    #              # This should only happen if there are multiple open channels to the target or a
    #              # channel has been closed while the session is still being used.
    #              logger.warning(
    #                  'Channels switched. Previous balance proofs not applicable to new channel.'
    #              )
    #
    #          self.channel = new_channel
    #      elif self.channel.remain_balance() < price:
    #          self.channel.topup(self.topup_deposit(price))
    #
    #      if self.channel is None:
    #          logger.error("No channel could be created or sufficiently topped up.")
    #          return False
    #
    #      self.channel.create_transfer(price)
    #      logger.debug(
    #          'Sending new balance proof. New channel balance: {}/{}'
    #          .format(self.channel.balance, self.channel.deposit)
    #      )
    #      return True
    #
    #  def on_http_error(self, method: str, url: str, response: Response, **requests_kwargs) -> bool:
    #      logger.error('Unexpected server error, status code {}'.format(response.status_code))
    #      return False
    #
    #  def on_init(self, method: str, url: str, **requests_kwargs):
    #      logger.debug('Starting {} request loop for resource at {}.'.format(method, url))
    #
    #  def on_exit(self, method: str, url: str, response: Response, **requests_kwargs):
    #      pass
    #
    #  def on_success(self, method: str, url: str, response: Response, **requests_kwargs) -> bool:
    #      logger.debug('Resource received.')
    #      cost = response.headers.get(HTTPHeaders.COST)
    #      if cost is not None:
    #          logger.debug('Final cost was {}.'.format(cost))
    #      return False
    #
    #  def on_invalid_contract_address(
    #          self,
    #          method: str,
    #          url: str,
    #          response: Response,
    #          **requests_kwargs
    #  ) -> bool:
    #      contract_address = response.headers.get(HTTPHeaders.CONTRACT_ADDRESS)
    #      logger.error(
    #          'Server sent no or invalid contract address: {}.'.format(contract_address)
    #      )
    #      return False
    #
    #
    #  def on_http_response(self, method: str, url: str, response: Response, **requests_kwargs) -> bool:
    #      """Called whenever server returns a reply.
    #      Return False to abort current request."""
    #      logger.debug('Response received: {}'.format(response.headers))
    #      return True
