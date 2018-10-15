# pyatn-client

**pyatn-client is Python ATN client, used to call DBot's API easily through payment channel**


## Install

Python ATN client depends on python3.6+, simply use pip3 to install, See [Installation](install.md) for detail.

```bash
pip3 install pyatn-client
```

## Usage

1. Use command `pyatn` to create an account and get some ATN if you don't have an account before.

```bash
pyatn create-account
pyatn get-atn --address <Address of Account>
```

2. There are various DBots which provide AI API on our [AI Market](https://market-test.atnio.net). Here is an example, use [AI poetry](https://market-test.atnio.net/detail/0xfd4f504f373f0af5ff36d9fbe1050e6300699230) to write poetry.

```python
from pyatn_client import Atn

DBOTADDRESS = '0xfd4F504F373f0af5Ff36D9fbe1050E6300699230' # address of the DBot you want to test, use 'AI poetry' as example
URI = '/reg'        # uri of the DBot's API endpoint which you want to call
METHOD = 'POST'     # method of the DBot's API endpoint which you want to call
requests_kwargs = {
    "data": {
        "theme": "中秋月更圆"
    }
}

# init Atn
atn = Atn(
    pk_file='<path to key file>',
    pw_file='<path to password file>'
)

# Call a DBot API 12 times
for i in range(12):
    response = atn.call_dbot_api(dbot_address=DBOTADDRESS,
                                uri=URI,
                                method=METHOD,
                                **requests_kwargs)
    print('Call {}:\n{}'.format(i + 1, response.text))

# close the channel only when you do not need it any more,
# the remain balance in the channel will be returned to your account
atn.close_channel(DBOTADDRESS)

```

In the example above, channel will be auto created if no one between your account and the DBot, and will be topuped if the remain balance in the channel is not enough.

The deposit value is determined by `deposit_strategy`, which is a callable function with price of endpoint as input parameter. The default deposit value is 10 times the price of endpoint.

This behavior can be changed, You can pass in `deposit_strategy` when init class `Atn` or use `set_deposit_strategy` method to change it. It can be set `None` to disable auto create or topup the channel, then you should create or topup channel by yourself before call the `call_dbot_api` method. Here is an example.


```python
from pyatn_client import Atn

DBOTADDRESS = '0xfd4F504F373f0af5Ff36D9fbe1050E6300699230' # address of the DBot you want to test
URI = '/reg'        # uri of the DBot's API endpoint which you want to call
METHOD = 'POST'     # method of the DBot's API endpoint which you want to call
requests_kwargs = {
    "data": {
        "theme": "中秋月更圆"
    }
}

# init Atn with deposit_strategy=None, it will disable auto create or topup channel.
atn = Atn(
    pk_file='<path to keystore file>',
    pw_file='<path to password file>',
    deposit_strategy=None,              # disable auto create or topup channel
)

# get price of the endpoint to be called
price = atn.get_price(DBOTADDRESS, URI, METHOD)
# open channel with the DBot, only one opened channel is allowed between two address
# it will return the channel if one existed.
channel = atn.open_channel(DBOTADDRESS, 10 * price)
# wait DBot server sync channel info with the blockchain
atn.wait_dbot_sync(DBOTADDRESS)
if channel.deposit - channel.balance < price:
    atn.topup_channel(DBOTADDRESS, 10 * price)
    # wait DBot server sync channel info with the blockchain
    atn.wait_dbot_sync(DBOTADDRESS)

# call DBot API 12 times
for i in range(12)
    print('Call {}:'.format(call_count))
    # AtnException will raise when eleventh call for insufficient balance, catch it in a production environment
    response = atn.call_dbot_api(dbot_address=DBOTADDRESS,
                                uri=URI,
                                method=METHOD,
                                **requests_kwargs)
    print('Call {}:\n{}'.format(i + 1, response.text))

```

## API Documentation

[API Documentation](https://pyatn-client-doc.atnio.net)
