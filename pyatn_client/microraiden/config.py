"""This module contains network-specific defaults for different networks.
You can change i.e. gas price, gas limits, or contract address here.

Example:
    Set global network defaults for ropsten::

        from config import NETWORK_CFG
        from constants import get_network_id

        NETWORK_CFG.set_defaults(get_network_id('ropsten'))

    Change global gas price::
    from config import NETWORK_CFG
        NETWORK_CFG.gas_price = 15 * denoms.gwei
"""
from eth_utils import denoms
from collections import namedtuple, OrderedDict
from functools import partial

# these are default values for network config
network_config_defaults = OrderedDict(
    (('channel_manager_address', None),
     ('start_sync_block', 0),
     ('gas_price', 20 * denoms.gwei),
     ('gas_limit', 130000),
     # pot = plain old transaction, for lack of better term
     ('pot_gas_limit', 21000))
)
# create network config type that supports defaults
NetworkConfig = partial(
    namedtuple(
        'NetworkConfig',
        network_config_defaults
    ),
    **network_config_defaults
)

# network-specific configuration
NETWORK_CONFIG_DEFAULTS = {
    # testnet
    17: NetworkConfig(
        channel_manager_address='0x0000000000000000000000000000000000000012',
        start_sync_block=0
    )
}

class NetworkRuntime:
    def __init__(self):
        super().__setattr__('cfg', None)

    def set_defaults(self, network_id: int):
        """Set global default settings for a given network id.

        Args:
            network_id (int): a network id to use.
        """
        cfg_copy = dict(NETWORK_CONFIG_DEFAULTS[network_id]._asdict())
        super().__setattr__('cfg', cfg_copy)

    def __getattr__(self, attr):
        return self.cfg.__getitem__(attr.lower())

    def __setattr__(self, attr, value):
        if attr == 'cfg':
            return super().__setattr__('cfg', value)
        return self.cfg.__setitem__(attr.lower(), value)


def get_defaults(network_id: int):
    return NETWORK_CONFIG_DEFAULTS[network_id]


# default config
NETWORK_CFG = NetworkRuntime()
NETWORK_CFG.set_defaults(17)
