from typing import List, Any, Union, Dict

import time
from web3 import Web3
from web3.contract import Contract
from eth_account import Account

from ..config import NETWORK_CFG
from ..utils.populus_compat import LogFilter

DEFAULT_TIMEOUT = 60
DEFAULT_RETRY_INTERVAL = 3


def signed_transaction(
    web3: Web3,
    account: Account,
    to: str,
    value: int,
) -> str:

    tx = {
        'to': to,
        'value': value,
        'gasPrice': web3.eth.gasPrice,
        'nonce': web3.eth.getTransactionCount(account.address),
        'chainId': int(web3.version.network)
    }
    return account.signTransaction(tx)


def signed_contract_transaction(
    account: Account,
    contract: Contract,
    func_sig: str,
    args: List[Any],
    value: int=0
):
    web3 = contract.web3
    tx_data = contract.get_function_by_signature(func_sig)(*args).buildTransaction({
            'from': account.address,
            'nonce': web3.eth.getTransactionCount(account.address),
            'gasPrice': web3.eth.gasPrice,
            'value': value
        })
    return account.signTransaction(tx_data)


def get_logs(
        contract: Contract,
        event_name: str,
        from_block: Union[int, str] = 0,
        to_block: Union[int, str] = 'pending',
        argument_filters: Dict[str, Any] = None
):
    event_abi = [
        abi_element for abi_element in contract.abi
        if abi_element['type'] == 'event' and abi_element['name'] == event_name
    ]
    assert len(event_abi) == 1, 'No event found matching name {}.'.format(event_name)
    event_abi = event_abi[0]

    if argument_filters is None:
        argument_filters = {}

    tmp_filter = LogFilter(
        contract.web3,
        [event_abi],
        contract.address,
        event_name,
        from_block,
        to_block,
        argument_filters
    )
    logs = tmp_filter.get_logs()
    tmp_filter.uninstall()
    return logs


def _get_logs_raw(contract: Contract, filter_params: Dict[str, Any]):
    """For easy patching."""
    return contract.web3._requestManager.request_blocking('eth_getLogs', [filter_params])


def get_event_blocking(
        contract: Contract,
        event_name: str,
        from_block: Union[int, str] = 0,
        to_block: Union[int, str] = 'latest',
        argument_filters: Dict[str, Any]=None,
        condition=None,
        wait=DEFAULT_RETRY_INTERVAL,
        timeout=DEFAULT_TIMEOUT
) -> Union[Dict[str, Any], None]:
    for i in range(0, timeout + wait, wait):
        logs = get_logs(
            contract,
            event_name,
            from_block=from_block,
            to_block=to_block,
            argument_filters=argument_filters
        )
        matching_logs = [event for event in logs if not condition or condition(event)]
        if matching_logs:
            return matching_logs[0]
        elif i < timeout:
            _wait(wait)

    return None


def _wait(duration: float):
    """For easy patching."""
    time.sleep(duration)


def wait_for_transaction(
        web3: Web3,
        tx_hash: str,
        timeout: int = DEFAULT_TIMEOUT,
        polling_interval: int = DEFAULT_RETRY_INTERVAL
):
    for waited in range(0, timeout + polling_interval, polling_interval):
        tx_receipt = web3.eth.getTransactionReceipt(tx_hash)
        if tx_receipt is not None:
            return tx_receipt
        if waited < timeout:
            _wait(polling_interval)
    raise TimeoutError('Transaction {} was not mined.'.format(tx_hash))
