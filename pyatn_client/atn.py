import os
import logging
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

log = logging.getLogger(__name__)

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
        initial_deposit: Callable[[int], int] = lambda price: 10 * price,
        topup_deposit: Callable[[int], int] = lambda price: 5 * price
    ) -> None:
        w3 = Web3(HTTPProvider(http_provider))
        w3.middleware_stack.inject(geth_poa_middleware, layer=0)

        self.initial_deposit = initial_deposit
        self.topup_deposit = topup_deposit

        self.channel = None  # type: Channel
        self.channel_client = Client(
            private_key=pk_file,
            key_password_path=pw_file,
            web3=w3
        )

    def get_dbot_name(self, dbot_address):
        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        name = Dbot.functions.name().call()
        return name.decode('utf-8').rstrip('\0')

    def get_dbot_domain(self, dbot_address):
        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        domain = Dbot.functions.domain().call()
        return domain.decode('utf-8').rstrip('\0')

    def get_price(self, dbot_address, uri, method):
        dbot_address = Web3.toChecksumAddress(dbot_address)
        w3 = self.channel_client.context.web3
        Dbot = _make_dbot_contract(w3, dbot_address)
        key = Dbot.functions.getKey(tobytes32(method.lower()), tobytes32(uri)).call()
        endpoint = Dbot.functions.keyToEndPoints(key).call()
        # TODO handle method case and how to check if the endpoint exist
        if (int(endpoint[1]) == 0):
            raise Exception('no such endpoint: uri = {}, method = {}'.format(uri, method))
        else:
            return int(endpoint[1])

    def get_dbot_channel(self, dbot_address):
        dbot_address = Web3.toChecksumAddress(dbot_address)
        domain = self.get_dbot_domain(dbot_address)
        channel = self._get_channel_info(dbot_address)
        backend = domain if domain.lower().startswith('http') else 'http://{}'.format(domain)
        if channel is not None:
            url = '{}/api/v1/dbots/{}/channels/{}/{}'.format(backend,
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
        if self.channel is None:
            log.warning('No Channel with dbot({}) on chain')
            return
        dbot_channel = self.get_dbot_channel(dbot_address)
        remain_times = retry_times
        while retry_times > 0 and (dbot_channel is None or int(dbot_channel['deposit']) != self.channel.deposit):
            log.info('Channel state with dbot({}) has not synced by dbot server, retry after {}s'.format(
                dbot_address, retry_interval))
            remain_times = remain_times - 1
            time.sleep(retry_interval)
            dbot_channel = self.get_dbot_channel(dbot_address)
        if dbot_channel is not None and int(dbot_channel['deposit']) == self.channel.deposit:
            self.channel.update_balance(int(dbot_channel['balance']))
        else:
            raise Exception('Channel state with dbot({}) can not synced by dbot server.'.format(dbot_address))

    def call_dbot_api(self, dbot_address: str, uri: str, method: str, **requests_kwargs) -> Response:
        #  if self.channel is None or self.channel.state != Channel.State.open:
        dbot_address = Web3.toChecksumAddress(dbot_address)
        price = self.get_price(dbot_address, uri, method)
        self.channel = self.channel_client.get_suitable_channel(
            dbot_address, price, self.initial_deposit, self.topup_deposit
        )
        if self.channel is None:
            log.error("No channel could be created or sufficiently topped up.")
            raise Exception('No channel could be created or sufficiently topped up.')

        self.wait_dbot_sync(dbot_address)

        if self.channel.remain_balance() < price:
            self.channel.topup(self.topup_deposit(price))
            self.wait_dbot_sync(dbot_address)

        self.channel.create_transfer(price)
        domain = self.get_dbot_domain(dbot_address)
        url = '{}/call/{}/{}'.format(domain if domain.lower().startswith('http') else 'http://{}'.format(domain),
                                     dbot_address, remove_slash_prefix(uri))
        return self._request_resource(method, url, **requests_kwargs)


    def close_channel(self, endpoint_url: str = None):
        if self.channel is None:
            log.debug('No channel to close.')
            return

        if endpoint_url is None:
            endpoint_url = self.endpoint_url

        if endpoint_url is None:
            log.warning('No endpoint URL specified to request a closing signature.')
            self.on_cooperative_close_denied()
            return

        log.debug(
            'Requesting closing signature from server for balance {} on channel {}/{}/{}.'
            .format(
                self.channel.balance,
                self.channel.sender,
                self.channel.sender,
                self.channel.block
            )
        )
        url = '{}/api/1/channels/{}/{}'.format(
            endpoint_url,
            self.channel.sender,
            self.channel.block
        )

        try:
            response = requests.request(
                'DELETE',
                url,
                data={'balance': self.channel.balance}
            )
        except requests.exceptions.ConnectionError as err:
            log.error(
                'Could not get a response from the server while requesting a closing signature: {}'
                .format(err)
            )
            response = None

        failed = True
        if response is not None and response.status_code == requests.codes.OK:
            closing_sig = response.json()['close_signature']
            failed = self.channel.close_cooperatively(decode_hex(closing_sig)) is None

        if response is None or failed:
            self.on_cooperative_close_denied(response)

    def on_cooperative_close_denied(self, response: Response = None):
        log.warning(
            'No valid closing signature received. Closing noncooperatively on a balance of 0.'
        )
        # if cooperative close denied, client close the dbot unilaterally
        self.channel.close(0)

    def _get_channel_info(self, receiver):
        open_channels = self.channel_client.get_open_channels(receiver)
        if open_channels:
            channel = open_channels[0]
            return channel
        else:
            return None

    def _request_resource(
            self,
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
        if self.channel is not None:
            headers.balance = str(self.channel.balance)
            headers.balance_signature = encode_hex(self.channel.balance_sig)
            headers.sender_address = self.channel.sender
            headers.receiver_address = self.channel.receiver
            headers.open_block = str(self.channel.block)

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
    #      log.warning('No Channel registered by DBot server')
    #      return True
    #
    #  def on_insufficient_confirmations(
    #          self,
    #          method: str,
    #          url: str,
    #          response: Response,
    #          **requests_kwargs
    #  ) -> bool:
    #      log.warning('Newly created channel does not have enough confirmations yet.')
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
    #      log.warning(
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
    #      log.debug('Server claims an invalid amount sent.')
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
    #              log.error(
    #                  'Server tried to disguise the last unconfirmed payment as a confirmed payment.'
    #              )
    #              return False
    #          else:
    #              log.debug(
    #                  'Server provided proof for a different channel balance ({}). Adopting.'.format(
    #                      last_balance
    #                  )
    #              )
    #              self.channel.update_balance(last_balance)
    #      else:
    #          log.debug(
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
    #      log.debug('Preparing payment of price {} to {}.'.format(price, receiver))
    #
    #      if self.channel is None or self.channel.state != Channel.State.open:
    #          new_channel = self.channel_client.get_suitable_channel(
    #              receiver, price, self.initial_deposit, self.topup_deposit
    #          )
    #
    #          if self.channel is not None and new_channel != self.channel:
    #              # This should only happen if there are multiple open channels to the target or a
    #              # channel has been closed while the session is still being used.
    #              log.warning(
    #                  'Channels switched. Previous balance proofs not applicable to new channel.'
    #              )
    #
    #          self.channel = new_channel
    #      elif self.channel.remain_balance() < price:
    #          self.channel.topup(self.topup_deposit(price))
    #
    #      if self.channel is None:
    #          log.error("No channel could be created or sufficiently topped up.")
    #          return False
    #
    #      self.channel.create_transfer(price)
    #      log.debug(
    #          'Sending new balance proof. New channel balance: {}/{}'
    #          .format(self.channel.balance, self.channel.deposit)
    #      )
    #      return True
    #
    #  def on_http_error(self, method: str, url: str, response: Response, **requests_kwargs) -> bool:
    #      log.error('Unexpected server error, status code {}'.format(response.status_code))
    #      return False
    #
    #  def on_init(self, method: str, url: str, **requests_kwargs):
    #      log.debug('Starting {} request loop for resource at {}.'.format(method, url))
    #
    #  def on_exit(self, method: str, url: str, response: Response, **requests_kwargs):
    #      pass
    #
    #  def on_success(self, method: str, url: str, response: Response, **requests_kwargs) -> bool:
    #      log.debug('Resource received.')
    #      cost = response.headers.get(HTTPHeaders.COST)
    #      if cost is not None:
    #          log.debug('Final cost was {}.'.format(cost))
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
    #      log.error(
    #          'Server sent no or invalid contract address: {}.'.format(contract_address)
    #      )
    #      return False
    #
    #
    #  def on_http_response(self, method: str, url: str, response: Response, **requests_kwargs) -> bool:
    #      """Called whenever server returns a reply.
    #      Return False to abort current request."""
    #      log.debug('Response received: {}'.format(response.headers))
    #      return True
