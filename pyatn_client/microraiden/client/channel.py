import os
import logging
from enum import Enum

from eth_utils import decode_hex, is_same_address
from typing import Callable

from .context import Context
from ..utils import (
    get_event_blocking,
    signed_contract_transaction,
    sign_balance_proof,
    verify_closing_sig,
    keccak256
)

logger = logging.getLogger('atn.microraiden' + os.path.splitext(os.path.basename(__file__))[0])

class Channel:
    class State(Enum):
        open = 1
        settling = 2
        closed = 3

    def __init__(
            self,
            core: Context,
            sender: str,
            receiver: str,
            block: int,
            deposit: int = 0,
            balance: int = 0,
            state: State = State.open,
            on_settle: Callable[['Channel'], None] = lambda channel: None
    ):
        self._balance = 0
        self._balance_sig = None

        self.core = core
        self.sender = sender
        self.receiver = receiver
        self.deposit = deposit
        self.block = block
        self.update_balance(balance)
        self.state = state
        self.on_settle = on_settle

        assert self.block is not None
        assert self._balance_sig

    @property
    def balance(self):
        return self._balance

    @property
    def key(self) -> bytes:
        return keccak256(self.sender, self.receiver, self.block)

    def update_balance(self, value):
        self._balance = value
        self._balance_sig = self.sign()

    @property
    def balance_sig(self):
        return self._balance_sig

    def sign(self):
        sig =  sign_balance_proof(
            self.core.private_key,
            self.receiver,
            self.block,
            self.balance,
            self.core.channel_manager.address
        )
        return sig

    def topup(self, deposit):
        """
        Attempts to increase the deposit in an existing channel. Block until confirmation.
        """
        if self.state != Channel.State.open:
            logger.error('Channel must be open to be topped up.')
            return

        _balance = self.core.web3.eth.getBalance(self.core.address)
        if _balance < deposit:
            logger.error(
                'Insufficient tokens available for the specified topup ({}/{})'
                .format(_balance, deposit)
            )
            return None

        logger.info('Topping up channel to {} created at block #{} by {} ATN.'.format(
            self.receiver, self.block, deposit
        ))
        current_block = self.core.web3.eth.blockNumber

        data = (decode_hex(self.sender) +
                decode_hex(self.receiver) +
                self.block.to_bytes(4, byteorder='big'))
        tx = signed_contract_transaction(
            self.core.account,
            self.core.channel_manager,
            'topUp(address,uint32)',
            [
                self.receiver,
                self.block
            ],
            deposit
        )
        self.core.web3.eth.sendRawTransaction(tx.rawTransaction)

        logger.debug('Waiting for topup confirmation event...')
        event = get_event_blocking(
            self.core.channel_manager,
            'ChannelToppedUp',
            from_block=current_block + 1,
            argument_filters={
                '_sender_address': self.sender,
                '_receiver_address': self.receiver,
                '_open_block_number': self.block
            }
        )

        if event:
            logger.debug('Successfully topped up channel in block {}.'.format(event['blockNumber']))
            self.deposit += deposit
            return event
        else:
            logger.error('No event received.')
            return None

    def close(self, balance=None):
        """
        Attempts to request close on a channel. An explicit balance can be given to override the
        locally stored balance signature. Blocks until a confirmation event is received or timeout.
        """
        if self.state != Channel.State.open:
            logger.error('Channel must be open to request a close.')
            return
        logger.info('Requesting close of channel to {} created at block #{}.'.format(
            self.receiver, self.block
        ))
        current_block = self.core.web3.eth.blockNumber

        if balance is not None:
            self.update_balance(balance)

        tx = signed_contract_transaction(
            self.core.account,
            self.core.channel_manager,
            'uncooperativeClose(address,uint32,uint256)',
            [
                self.receiver,
                self.block,
                self.balance
            ]
        )
        self.core.web3.eth.sendRawTransaction(tx.rawTransaction)

        logger.debug('Waiting for close confirmation event...')
        event = get_event_blocking(
            self.core.channel_manager,
            'ChannelCloseRequested',
            from_block=current_block + 1,
            argument_filters={
                '_sender_address': self.sender,
                '_receiver_address': self.receiver,
                '_open_block_number': self.block
            }
        )

        if event:
            logger.debug('Successfully sent channel close request in block {}.'.format(
                event['blockNumber']
            ))
            self.state = Channel.State.settling
            return event
        else:
            logger.error('No event received.')
            return None

    def close_cooperatively(self, closing_sig: bytes, contract_receiver_owner: str = None):
        """
        Attempts to close the channel immediately by providing a hash of the channel's balance
        proof signed by the receiver. This signature must correspond to the balance proof stored in
        the passed channel state.
        """
        if self.state == Channel.State.closed:
            logger.error('Channel must not be closed already to be closed cooperatively.')
            return None
        logger.info('Attempting to cooperatively close channel to {} created at block #{}.'.format(
            self.receiver, self.block
        ))
        current_block = self.core.web3.eth.blockNumber
        receiver_recovered = verify_closing_sig(
            self.sender,
            self.block,
            self.balance,
            closing_sig,
            self.core.channel_manager.address
        )
        bytecode = self.core.web3.eth.getCode(self.receiver)
        if bytecode:
            # The channel's receiver is a contract, the close_signature should be signed by it's owner
            assert(contract_receiver_owner is not None)
            if contract_receiver_owner is not None and not is_same_address(receiver_recovered, contract_receiver_owner):
                logger.error('Invalid closing signature')
                return None
        else:
            if not is_same_address(receiver_recovered, self.receiver):
                logger.error('Invalid closing signature.')
                return None

        tx = signed_contract_transaction(
            self.core.account,
            self.core.channel_manager,
            'cooperativeClose(address,uint32,uint256,bytes,bytes)',
            [
                self.receiver,
                self.block,
                self.balance,
                self.balance_sig,
                closing_sig
            ]
        )
        self.core.web3.eth.sendRawTransaction(tx.rawTransaction)

        logger.debug('Waiting for settle confirmation event...')
        event = get_event_blocking(
            self.core.channel_manager,
            'ChannelSettled',
            from_block=current_block + 1,
            argument_filters={
                '_sender_address': self.sender,
                '_receiver_address': self.receiver,
                '_open_block_number': self.block
            }
        )

        if event:
            logger.debug('Successfully closed channel in block {}.'.format(event['blockNumber']))
            self.state = Channel.State.closed
            return event
        else:
            logger.error('No event received.')
            return None

    def settle(self):
        """
        Attempts to settle a channel that has passed its settlement period. If a channel cannot be
        settled yet, the call is ignored with a warning. Blocks until a confirmation event is
        received or timeout.
        """
        if self.state != Channel.State.settling:
            logger.error('Channel must be in the settlement period to settle.')
            return None
        logger.info('Attempting to settle channel to {} created at block #{}.'.format(
            self.receiver, self.block
        ))

        _, _, settle_block, _, _ = self.core.channel_manager.call().getChannelInfo(
            self.sender, self.receiver, self.block
        )

        current_block = self.core.web3.eth.blockNumber
        wait_remaining = settle_block - current_block
        if wait_remaining > 0:
            logger.warning('{} more blocks until this channel can be settled. Aborting.'.format(
                wait_remaining
            ))
            return None

        tx = signed_contract_transaction(
            self.core.account,
            self.core.channel_manager,
            'settle(address,uint32)',
            [
                self.receiver,
                self.block
            ]
        )
        self.core.web3.eth.sendRawTransaction(tx.rawTransaction)

        logger.debug('Waiting for settle confirmation event...')
        event = get_event_blocking(
            self.core.channel_manager,
            'ChannelSettled',
            from_block=current_block + 1,
            argument_filters={
                '_sender_address': self.sender,
                '_receiver_address': self.receiver,
                '_open_block_number': self.block
            }
        )

        if event:
            logger.debug('Successfully settled channel in block {}.'.format(event['blockNumber']))
            self.state = Channel.State.closed
            self.on_settle(self)
            return event
        else:
            logger.error('No event received.')
            return None

    def create_transfer(self, value):
        """
        Updates the given channel's balance and balance signature with the new value. The signature
        is returned and stored in the channel state.
        """
        assert value >= 0
        if self.remain_balance() < value:
            logger.error(
                'Insufficient funds on channel. Needed: {}. Available: {}/{}.'
                .format(value, self.deposit - self.balance, self.deposit)
            )
            return None

        logger.debug('Signing new transfer of value {} on channel to {} created at block #{}.'.format(
            value, self.receiver, self.block
        ))

        if self.state == Channel.State.closed:
            logger.error('Channel must be open to create a transfer.')
            return None

        self.update_balance(self.balance + value)

        return self.balance_sig

    def is_valid(self) -> bool:
        return self.sign() == self.balance_sig and self.balance <= self.deposit

    def remain_balance(self) -> int:
        return self.deposit - self.balance

    def is_suitable(self, value: int):
        return self.remain_balance() >= value
