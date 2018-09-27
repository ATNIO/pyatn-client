#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import re
import json
import click
import importlib.util
#  import requests
import logging
#  from eth_utils import is_same_address, decode_hex

#  from microraiden.config import NETWORK_CFG
#  from microraiden.utils import privkey_to_addr, verify_balance_proof, create_signed_contract_transaction
#  from microraiden.make_helpers import make_channel_manager_contract
from pyatn_client import Atn

def load_module(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, os.path.join(path, module_name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@click.group()
def cli():
    pass

@cli.command()
@click.option(
    '--pk-file',
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    required=True,
    help='Path to private key file or a hex-encoded private key.'
)
@click.option(
    '--pw-file',
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    required=True,
    help='Path to file containing the password for the private key specified.'
)
@click.option(
    '--http-provider',
    required=True,
    help='Http Provider'
)
@click.option(
    '--dbot-address',
    required=True,
    help='dbot address')
@click.option(
    '--data',
    required=True,
    help='requests test data')
def call(
        pk_file: str,
        pw_file: str,
        http_provider: str,
        dbot_address: str,
        data: str
):
    """
    For API comsumer to Call DBot's API.
    The requests test data looks like:
    {
        # which endpoint to be called in the DBot
        "endpoint": {
            "uri": "/reg",
            "method": "POST"
        },
        # kwargs for `requests` to send HTTP request
        "kwargs": {
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded"
            },
            "data": {
                "theme": "每逢佳节你更圆"
            }
        }
    }
    """

    requests_test = load_module(os.path.splitext(os.path.basename(data))[0],
                                os.path.dirname(os.path.abspath(data)))
    requests_data = requests_test.data

    atn = Atn(
        http_provider=http_provider,
        pk_file=pk_file,
        pw_file=pw_file
    )

    response = atn.call_dbot_api(dbot_address,
                                 uri=requests_data['endpoint']['uri'],
                                 method=requests_data['endpoint']['method'],
                                 **requests_data['kwargs'])

    if response.status_code == 200:
        click.echo('Got 200 Response. Content-Type: {}'.format(response.headers['Content-Type']))
        if re.match('^json/', response.headers['Content-Type']):
            click.echo(response.headers)
            click.echo(response.json)
        elif response.headers['Content-Type'].startswith('audio') or response.headers['Content-Type'].startswith('image'):
            click.echo(response.headers)
            response_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'response_file')
            with open(response_file, 'wb') as f:
                f.write(response.content)
            click.echo('Save response file at {}'.format(response_file))
        else:
            click.echo(response.headers)
            click.echo(response.text)
    else:
        click.echo('Got {} Response.'.format(response.status_code))
        click.echo(response.text)


#  @cli.command()
#  @click.option(
#      '--pk_file',
#      required=True,
#      help='Path to private key file or a hex-encoded private key.'
#  )
#  @click.option(
#      '--pw_file',
#      default=None,
#      help='Path to file containing the password for the private key specified.',
#      type=click.Path(exists=True, dir_okay=False, resolve_path=True)
#  )
#  @click.option(
#      '--http_provider',
#      default='http://0.0.0.0:8545',
#      help='Http Provider'
#  )
#  @click.option('--dbot_address', required=True, help='dbot address')
#  @click.option('--channel_manager_address', default='', help='channel manager contract address')
#  def close(
#      pk_file: str,
#      pw_file: str,
#      http_provider: str,
#      dbot_address: str,
#      channel_manager_address: str
#  ):
#      # TODO 1. get close signature from receiver, 2. send tx to close channels
#      # TODO select which channel to close (close the first channel now, we should allow one channel for one
#      # dbot later)
#      w3 = Web3(HTTPProvider(http_provider))
#      w3.middleware_stack.inject(geth_poa_middleware, layer=0)
#
#      dbot_address = Web3.toChecksumAddress(dbot_address)
#      dbot_contract = w3.eth.contract(address=dbot_address, abi=abi)
#      dbot_domain = Web3.toBytes(dbot_contract.functions.domain().call()).decode('utf-8').rstrip('\0')
#
#      channel_client = Client(
#          private_key=pk_file,
#          key_password_path=pw_file,
#          web3=w3
#      )
#
#      channels = channel_client.get_open_channels(dbot_address)
#
#      pending_txs = []
#
#      if not channels:
#          click.echo('No channels')
#          raise click.Abort()
#      for channel in channels:
#          click.echo('Close all channels with Dbot: {}'.format(dbot_address))
#          # request close signature from dbot server
#          #  channel.update_balance(balance)
#
#          # Get last balance signature from server first
#          private_key = get_private_key(pk_file, pw_file)
#          url = 'http://{}/api/v1/dbots/{}/channels/{}/{}'.format(
#              dbot_domain,
#              dbot_address,
#              privkey_to_addr(private_key),
#              channel.block
#          )
#          r = requests.get(url)
#          if r.status_code != 200:
#              click.echo("Can not get channel info from server")
#              raise click.Abort()
#
#          channel_info = r.json()
#          balance_sig = channel_info['last_signature']
#          last_balance = channel_info['balance']
#
#          verified = balance_sig and is_same_address(
#              verify_balance_proof(
#                  channel.receiver,
#                  channel.block,
#                  last_balance,
#                  decode_hex(balance_sig),
#                  channel_client.context.channel_manager.address
#              ),
#              channel.sender
#          )
#
#          if verified:
#              if last_balance == channel.balance:
#                  click.echo(
#                      'Server tried to disguise the last unconfirmed payment as a confirmed payment.'
#                  )
#                  raise click.Abort()
#              else:
#                  click.echo(
#                      'Server provided proof for a different channel balance ({}). Adopting.'.format(
#                          last_balance
#                      )
#                  )
#                  channel.update_balance(last_balance)
#          else:
#              click.echo(
#                  'Server did not provide proof for a different channel balance. Reverting to 0.'
#              )
#              channel.update_balance(0)
#
#          # Get close signature
#          r = requests.delete(url, data = {'balance': channel.balance})
#          if r.status_code != 200:
#              click.echo("Can not get close signature form server.")
#              click.echo(r.text)
#              raise click.Abort()
#          closing_sig = r.json().get('close_signature')
#          print('Got close signature: {}'.format(closing_sig))
#
#          channel_manager_address = channel_manager_address or NETWORK_CFG.CHANNEL_MANAGER_ADDRESS
#          channel_manager_contract = make_channel_manager_contract(w3, channel_manager_address)
#          raw_tx = create_signed_contract_transaction(
#              private_key,
#              channel_manager_contract,
#              'cooperativeClose',
#              [
#                  channel.receiver,
#                  channel.block,
#                  channel.balance,
#                  decode_hex(balance_sig),
#                  decode_hex(closing_sig)
#              ]
#          )
#          tx_hash = w3.eth.sendRawTransaction(raw_tx)
#          click.echo('Sending cooperative close tx (hash: {})'.format(tx_hash.hex()))
#          pending_txs.append(tx_hash)
#
#      for tx_hash in pending_txs:
#          click.echo("wait for tx to be mined")
#          tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
#
#      click.echo("All channels with the dbot are closed")
#      print(tx_receipt)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    cli()
