import os
import logging
from typing import List

import os
from eth_utils import decode_hex, is_same_address, is_hex, remove_0x_prefix, to_checksum_address
from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.utils.filters import Filter

from ..utils import (
    get_private_key,
    get_logs,
    get_event_blocking,
    signed_contract_transaction,
    signed_contract_transaction
)

from ..config import NETWORK_CFG
from ..constants import WEB3_PROVIDER_DEFAULT
from .context import Context
from .channel import Channel

logger = logging.getLogger('atn.microraiden' + os.path.splitext(os.path.basename(__file__))[0])


class Client:
    def __init__(
            self,
            private_key: str = None,
            key_password_path: str = None,
            channel_manager_address: str = None,
            web3: Web3 = None
    ) -> None:
        is_hex_key = is_hex(private_key) and len(remove_0x_prefix(private_key)) == 64
        is_path = os.path.exists(private_key)
        assert is_hex_key or is_path, 'Private key must either be a hex key or a file path.'

        # Load private key from file if none is specified on command line.
        if is_path:
            private_key = get_private_key(private_key, key_password_path)
            assert private_key is not None, 'Could not load private key from file.'

        self.channels = []  # type: List[Channel]

        # Create web3 context if none is provided, either by using the proxies' context or creating
        # a new one.
        if not web3:
            web3 = Web3(HTTPProvider(WEB3_PROVIDER_DEFAULT))

        channel_manager_address = to_checksum_address(
            channel_manager_address or NETWORK_CFG.CHANNEL_MANAGER_ADDRESS
        )

        self.context = Context(private_key, web3, channel_manager_address)

        self.sync_channels()

    def sync_channels(self):
        filter_kwargs = {
            'fromBlock': 0,
            'toBlock': 'latest'
        }
        filters = {'_sender_address': self.context.address}
        create = self.context.channel_manager.events.ChannelCreated.createFilter(
            argument_filters=filters,
            **filter_kwargs).get_all_entries()

        topup = self.context.channel_manager.events.ChannelToppedUp.createFilter(
            argument_filters=filters,
            **filter_kwargs).get_all_entries()

        close = self.context.channel_manager.events.ChannelCloseRequested.createFilter(
            argument_filters=filters,
            **filter_kwargs).get_all_entries()

        settle = self.context.channel_manager.events.ChannelSettled.createFilter(
            argument_filters=filters,
            **filter_kwargs).get_all_entries()

        channel_key_to_channel = {}

        def get_channel(event) -> Channel:
            sender = to_checksum_address(event['args']['_sender_address'])
            receiver = to_checksum_address(event['args']['_receiver_address'])
            block = event['args'].get('_open_block_number', event['blockNumber'])
            assert is_same_address(sender, self.context.address)
            return channel_key_to_channel.get((sender, receiver, block), None)

        for c in self.channels:
            channel_key_to_channel[(c.sender, c.receiver, c.block)] = c

        for e in create:
            c = get_channel(e)
            if c:
                c.deposit = e['args']['_deposit']
            else:
                c = Channel(
                    self.context,
                    to_checksum_address(e['args']['_sender_address']),
                    to_checksum_address(e['args']['_receiver_address']),
                    e['blockNumber'],
                    e['args']['_deposit'],
                    on_settle=lambda channel: self.channels.remove(channel)
                )
                assert is_same_address(c.sender, self.context.address)
                channel_key_to_channel[(c.sender, c.receiver, c.block)] = c

        for e in topup:
            c = get_channel(e)
            c.deposit += e['args']['_added_deposit']

        for e in close:
            # Requested closed, not actual closed.
            c = get_channel(e)

            c.update_balance(e['args']['_balance'])
            c.state = Channel.State.settling

        for e in settle:
            c = get_channel(e)
            c.state = Channel.State.closed

        # Forget closed channels.
        self.channels = [
            c for c in channel_key_to_channel.values() if c.state != Channel.State.closed
        ]

        logger.debug('Synced a total of {} channels.'.format(len(self.channels)))

    def open_channel(self, receiver_address: str, deposit: int):
        """
        Attempts to open a new channel to the receiver with the given deposit. Blocks until the
        creation transaction is found in a pending block or timeout is reached. The new channel
        state is returned.
        """
        assert isinstance(receiver_address, str)
        assert isinstance(deposit, int)
        assert deposit > 0

        balance = self.context.web3.eth.getBalance(self.context.address)
        #  token_balance = self.context.token.call().balanceOf(self.context.address)
        if balance < deposit:
            logger.error(
                'Insufficient balance available for the specified deposit ({}/{})'
                .format(balance, deposit)
            )
            return None

        current_block = self.context.web3.eth.blockNumber
        logger.info('Creating channel to {} with an initial deposit of {} @{}'.format(
            receiver_address, deposit, current_block
        ))

        tx = signed_contract_transaction(
            self.context.account,
            self.context.channel_manager,
            'createChannel(address)',
            [
                receiver_address
            ],
            deposit
        )
        ret = self.context.web3.eth.sendRawTransaction(tx.rawTransaction)
        logger.info('transaction hash: {}'.format(Web3.toHex(ret)))

        logger.debug('Waiting for channel creation event on the blockchain...')
        filters = {
            '_sender_address': self.context.address,
            '_receiver_address': receiver_address
        }
        event = get_event_blocking(
            self.context.channel_manager,
            'ChannelCreated',
            from_block=current_block + 1,
            to_block='latest',
            argument_filters=filters
        )

        if event:
            logger.debug('Event received. Channel created in block {}.'.format(event['blockNumber']))
            assert is_same_address(event['args']['_sender_address'], self.context.address)
            assert is_same_address(event['args']['_receiver_address'], receiver_address)
            channel = Channel(
                self.context,
                self.context.address,
                receiver_address,
                event['blockNumber'],
                event['args']['_deposit'],
                on_settle=lambda c: self.channels.remove(c)
            )
            self.channels.append(channel)
        else:
            logger.error('Error: No event received.')
            channel = None

        return channel

    def topup_channel(self, receiver_address: str, deposit: int):
        open_channels = self.get_open_channels(receiver_address)
        if open_channels:
            capacity, channel = max(
                ((c.deposit - c.balance, c) for c in open_channels), key=lambda x: x[0]
            )
            event = channel.topup(deposit)
            return channel if event else None
        else:
            logger.error('Error: No channel to top up')
            return None

    def get_channels(self, receiver: str = None) -> List[Channel]:
        return [
            c for c in self.channels
            if is_same_address(c.sender, self.context.address) and
            (not receiver or is_same_address(c.receiver, receiver))
        ]

    def get_open_channels(self, receiver: str = None) -> List[Channel]:
        """
        Returns all open channels to the given receiver. If no receiver is specified, all open
        channels are returned.
        """
        return [
            c for c in self.channels
            if is_same_address(c.sender, self.context.address) and
            (not receiver or is_same_address(c.receiver, receiver)) and
            c.state == Channel.State.open
        ]

    def get_suitable_channel(
            self, receiver, value, initial_deposit=None, topup_deposit=None
    ) -> Channel:
        """
        Searches stored channels for one that can sustain the given transfer value. If none is
        found, a possibly open channel is topped up using the topup callable to determine its topup
        value. If both attempts fail, a new channel is created based on the initial deposit
        callable.
        Note: In the realistic case that only one channel is opened per (sender,receiver) pair,
        this method usually performs like this:
        1. Directly return open channel if sufficiently funded.
        2. Topup existing open channel if insufficiently funded.
        3. Create new channel if no open channel exists.
        If topping up or creating fails, this method returns None.
        Channels are topped up just enough so that their remaining capacity equals
        topup_deposit(value).
        """
        open_channels = self.get_open_channels(receiver)
        suitable_channels = [c for c in open_channels if c.is_suitable(value)]

        if suitable_channels:
            # At least one channel with sufficient funds.

            if len(suitable_channels) > 1:
                # This is not impossible but should only happen after bad channel management.
                logger.warning(
                    'Warning: {} suitable channels found. '
                    'Choosing the one with the lowest remaining capacity.'
                    .format(len(suitable_channels))
                )

            capacity, channel = min(
                ((c.deposit - c.balance, c) for c in suitable_channels), key=lambda x: x[0]
            )
            logger.debug(
                'Found suitable open channel, opened at block #{}.'.format(channel.block)
            )
            return channel

        elif open_channels:
            # Open channel(s) but insufficient funds. Requires topup.

            if len(open_channels) > 1:
                # This is not impossible but should only happen after bad channel management.
                logger.warning(
                    'Warning: {} open channels for topup found. '
                    'Choosing the one with the highest remaining capacity.'
                    .format(len(open_channels))
                )

            capacity, channel = max(
                ((c.deposit - c.balance, c) for c in open_channels), key=lambda x: x[0]
            )
            deposit = max(value, topup_deposit(value)) - capacity
            event = channel.topup(deposit)
            return channel if event else None

        else:
            # No open channels to receiver. Create a new one.
            deposit = max(value, initial_deposit(value))
            return self.open_channel(receiver, deposit)
