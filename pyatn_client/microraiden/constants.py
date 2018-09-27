"""
This file contains configuration constants you probably don't need to change
"""
import json
import os

def read_version(path: str):
    return open(path, 'r').read().strip()

# api path prefix
API_PATH = "/api/1"
"""str: api path prefix"""

#  MICRORAIDEN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
"""str: absolute path to module directory. Used to find path to the webUI sources"""
#  HTML_DIR = os.path.join(MICRORAIDEN_DIR, 'microraiden', 'webui')
"""str: webUI sources directory"""
#  JSLIB_DIR = os.path.join(HTML_DIR, 'js')
"""str: javascript directory"""
#  JSPREFIX_URL = '/js'
"""str: url prefix for jslib dir"""

WEB3_PROVIDER_DEFAULT = "http://0.0.0.0:8545"
"""str: ethereum node RPC interface URL"""

CHANNEL_MANAGER_NAME = 'TransferChannels'
"""str: name of the channel manager contract"""

CONTRACTS_JSON = 'contracts.json'
"""str: compiled contracts path"""

with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), CONTRACTS_JSON)) as fh:
    CONTRACT_METADATA = json.load(fh)

PROXY_BALANCE_LIMIT = 10**8
"""int: proxy will stop serving requests if receiver balance is below PROXY_BALANCE_LIMIT"""
SLEEP_RELOAD = 2
