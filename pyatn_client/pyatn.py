#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import json
import click
import importlib.util
import logging
import getpass
import requests
import time
from web3 import Web3, HTTPProvider
from web3.middleware import geth_poa_middleware

from eth_account import Account

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
    '--output',
    default='keystore',
    help='Path to privatekey file and password file of the created account'
)
def create_account(output):
    """
    Create an encrypted account on ATN test net.
    """
    acct = Account.create()
    password = getpass.getpass("Enter the password to encrypt your account: ")
    encrypted = Account.encrypt(acct.privateKey, password)
    os.makedirs(output, exist_ok=True)
    acct_path = os.path.join(output, acct.address)
    os.makedirs(acct_path, exist_ok=True)
    pk_file = os.path.join(acct_path, 'privatekey')
    pw_file = os.path.join(acct_path, 'password')
    with open(pk_file, 'w') as fh:
        fh.write(json.dumps(encrypted, indent=2))
    with open(pw_file, 'w') as fh:
        fh.write(password)
    click.echo('A new account {} created.'.format(acct.address))
    click.echo('The private  file saved at {}'.format(os.path.abspath(pk_file)))
    click.echo('The password file saved at {}'.format(os.path.abspath(pw_file)))

@cli.command()
@click.option(
    '--address',
    required=True,
    help='Address of the account to request ATN'
)
def get_atn(address):
    """
    Get ATN from the faucet server of ATN test net
    """
    w3 = Web3(HTTPProvider('https://rpc-test.atnio.net'))
    w3.middleware_stack.inject(geth_poa_middleware, layer=0)
    click.echo('ATN Balance is: {} ATN'.format(w3.fromWei(w3.eth.getBalance(address), 'ether')))
    resp = requests.post('http://119.3.57.66:4111/faucet/{}'.format(address))
    if resp.status_code == 200:
        click.echo('Get 100 ATN successfully. (One address can get 100 ATN everyday.)')
        click.echo('Waiting 10 second for the transaction finished ...')
        for i in range(10, 0, -1):
            time.sleep(1)
            click.echo(i)
        click.echo('ATN Balance is: {} ATN'.format(w3.fromWei(w3.eth.getBalance(address), 'ether')))
    else:
        click.echo('Can not get ATN. Try to visit out faucet page "https://faucet-test.atnio.net/"')

@cli.command()
@click.option(
    '--address',
    required=True,
    help='Address of the account to request ATN'
)
def get_balance(address):
    w3 = Web3(HTTPProvider('https://rpc-test.atnio.net'))
    w3.middleware_stack.inject(geth_poa_middleware, layer=0)
    click.echo('ATN Balance is: {} ATN'.format(w3.fromWei(w3.eth.getBalance(address), 'ether')))

@cli.command()
@click.option(
    '--pk-file',
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    required=True,
    help='Path to private key file'
)
@click.option(
    '--pw-file',
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    required=True,
    help='Path to file containing the password for the private key specified.'
)
@click.option(
    '--http-provider',
    default='https://rpc-test.atnio.net',
    help='Web3 Http Provider, default is https://rpc-test.atnio.net'
)
@click.option(
    '--dbot-address',
    required=True,
    help='Address of the DBot contract'
)
@click.option(
    '--data',
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    required=True,
    help="Path to python file containing requests data for the DBot API"
)
def call(
        pk_file: str,
        pw_file: str,
        http_provider: str,
        dbot_address: str,
        data: str
):
    """
    Call an API of the DBot.

    """

    requests_test = load_module(os.path.splitext(os.path.basename(data))[0],
                                os.path.dirname(os.path.abspath(data)))
    requests_data = requests_test.data

    atn = Atn(
        http_provider=http_provider,
        pk_file=pk_file,
        pw_file=pw_file
    )

    #  channel = atn.get_suitable_channel(dbot_address, requests_data['endpoint']['uri'], requests_data['endpoint']['method'])
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


@cli.command()
@click.option(
    '--pk-file',
    required=True,
    help='Path to private key file or a hex-encoded private key.'
)
@click.option(
    '--pw-file',
    default=None,
    help='Path to file containing the password for the private key specified.',
    type=click.Path(exists=True, dir_okay=False, resolve_path=True)
)
@click.option(
    '--http-provider',
    default='https://rpc-test.atnio.net',
    help='Web3 Http Provider, default is https://rpc-test.atnio.net'
)
@click.option('--dbot-address', required=True, help='dbot address')
def close(
    pk_file: str,
    pw_file: str,
    http_provider: str,
    dbot_address: str,
):
    """
    Close the channel with a DBot.
    """
    atn = Atn(
        http_provider=http_provider,
        pk_file=pk_file,
        pw_file=pw_file
    )

    atn.close_channel(dbot_address)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    cli()
